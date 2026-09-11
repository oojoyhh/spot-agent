"""UI → Agent 호출 경계.

담당: 역할 6 · 명하 · feature/ui
명세: docs/00_공통계약.md 4절, docs/06_Streamlit_Integration.md

UI가 Agent와 주고받는 유일한 통로다.
`run_analysis(request, context) -> StudySpotResponse` 외의 경로로
data Tool·점수 Tool·Store를 호출하지 않는다.

역할 5(석휘)의 `agent.main_agent.run_analysis`가 아직 없으므로,
없을 때는 화면 개발용 stub이 응답한다. stub 응답은 전부 `is_mock=True` 근거를 달고
`BACKEND` 값으로 화면 상단에 실제 Agent 미연결 상태를 표시한다.

TODO(역할 5): 진입점 시그니처·동기/비동기 여부 확정 후 아래 import 경로 확인.
TODO(역할 3): 타임아웃·재시도·Guardrail 차단 메시지 규약 확정 후 예외 처리 보강.
"""

from __future__ import annotations

import os
import importlib
import uuid
from typing import Any

from ui.contracts import (
    AgentRequest,
    AreaRecommendation,
    BusinessConditions,
    EvidenceItem,
    PendingActionView,
    RuntimeContext,
    StudySpotResponse,
)

FORCE_STUB = os.getenv("STUDYSPOT_FORCE_STUB", "").strip().lower() in {"1", "true", "yes", "on"}

#: 사용할 Agent 모듈. 다른 모듈로 바꾸려면 .env에 STUDYSPOT_AGENT_MODULE을 넣는다.
#: 어느 모듈을 쓰는지는 사이드바 "Agent 진입점"에 그대로 표시된다.
AGENT_MODULE = os.getenv("STUDYSPOT_AGENT_MODULE", "agent.main_agent_example").strip()

try:  # pragma: no cover - 역할 5 PR merge 후 이 경로만 남는다
    if FORCE_STUB:
        raise ImportError("stub mode requested")
    _run_analysis = getattr(
        importlib.import_module(AGENT_MODULE), "run_analysis"
    )  # type: ignore[assignment]

    BACKEND = AGENT_MODULE
except (ImportError, AttributeError) as _agent_import_error:
    _run_analysis = None
    if FORCE_STUB:
        BACKEND = "stub (forced)"
    else:
        # 모듈 이름 오타·미구현을 stub과 구분해 사이드바에 그대로 보여 준다.
        BACKEND = f"stub ({AGENT_MODULE} 불러오기 실패: {_agent_import_error})"

AGENT_CONNECTED = _run_analysis is not None
FAVORITE_MESSAGE_PREFIX = "관심 상권 저장 요청:"


def build_favorite_message(commercial_area_id: str) -> str:
    return f"{FAVORITE_MESSAGE_PREFIX} {commercial_area_id}"

#: stub이 지원하는 데모 상태. 사이드바에서 선택해 화면을 확인한다.
STUB_SCENARIOS: tuple[str, ...] = (
    "자동 (입력값에 따름)",
    "success",
    "success (일부 지표 누락·Mock 혼합)",
    "need_more_information",
    "no_result",
    "no_result (시스템 오류)",
    "approval_required",
)


def call_agent(
    request: AgentRequest,
    context: RuntimeContext,
    *,
    stub_scenario: str = "자동 (입력값에 따름)",
) -> StudySpotResponse:
    """호출 경계. 실제 Agent가 있으면 그쪽으로, 없으면 stub으로 넘긴다.

    UI는 State를 전달하거나 수정하지 않는다. 승인 의도도 이 경계로만 전달한다.
    """
    if _run_analysis is not None:
        return _run_analysis(request, context)
    return _stub_run_analysis(request, context, stub_scenario)


# --- 화면 개발용 stub -----------------------------------------------------------
# 역할 5의 진입점이 연결되면 아래 블록은 삭제하고, 대신 data/mock/ui_*.json fixture로
# 테스트(UI-01, INT-01~09)를 구성한다.


def _missing_required(conditions: BusinessConditions) -> list[str]:
    required = (
        "preferred_region",
        "deposit_budget",
        "monthly_rent_budget",
        "target_age",
        "operating_start_time",
        "operating_end_time",
    )
    return [f for f in required if getattr(conditions, f, None) is None]


def _stub_run_analysis(
    request: AgentRequest,
    context: RuntimeContext,
    scenario: str,
) -> StudySpotResponse:
    # 사이드바에서 명시적으로 선택한 Stub 시나리오
    if scenario.startswith("success (일부"):
        return _stub_partial_success()
    if scenario == "success":
        return _stub_success()
    if scenario == "need_more_information":
        return _stub_need_more(
            ["monthly_rent_budget", "operating_end_time"]
        )
    if scenario == "no_result":
        return _stub_no_result()
    if scenario.startswith("no_result (시스템"):
        return _stub_system_error()
    if scenario == "approval_required":
        return _stub_approval_required(context)

    # 이하: "자동 (입력값에 따름)" 시나리오

    if request.message and request.message.startswith(
        FAVORITE_MESSAGE_PREFIX
    ):
        return StudySpotResponse(
            status="no_result",
            recommendations=[],
            message=(
                "[stub] 즐겨찾기 저장 요청을 확인했습니다. "
                "Agent가 연결되지 않아 실제 Store에는 저장되지 않았습니다."
            ),
        )

    # 승인 요청에는 business_conditions가 없으므로 먼저 검사
    if request.approval_decision is not None:
        return _stub_after_decision(request)

    conditions = request.business_conditions or BusinessConditions()
    missing = _missing_required(conditions)

    if missing:
        return _stub_need_more(missing)

    return _stub_partial_success()


def _ev(
    source: str,
    summary: str,
    is_mock: bool = True,
    *,
    tool_name: str | None = None,
    metric_name: str | None = None,
    value: float | None = None,
    unit: str | None = None,
) -> Any:
    """화면 확인용 근거. 실제 Agent가 채우는 모양과 같은 형태로 만든다.

    공통 모델 규칙: value를 넣으면 tool_name·metric_name·unit을 함께 넣어야 한다.
    """
    return EvidenceItem(
        source=source,
        summary=summary,
        is_mock=is_mock,
        tool_name=tool_name,
        metric_name=metric_name,
        value=value,
        unit=unit,
    )


def _stub_success() -> StudySpotResponse:
    recs = [
        AreaRecommendation(
            area_name="[stub] 상권 A",
            commercial_area_id="STUB-A",
            academy_demand_score=21.0,
            target_customer_score=16.0,
            station_traffic_score=12.0,
            activity_score=11.0,
            rent_score=9.0,
            competition_score=7.0,
            total_score=76.0,
            strengths=[
                "[stub] 반경 500m 안에 입시학원이 42곳으로 후보 중 가장 많음",
                "[stub] 인근 역 통행량이 평일 18~22시에 몰려 있어 운영 시간과 겹침",
            ],
            risks=[
                "[stub] 같은 상권에 스터디카페 9곳이 이미 있어 경쟁 점수가 낮음",
                "[stub] 평균 월세가 입력한 예산 상단에 근접함",
            ],
            evidence=[
                _ev("stub:academy", "반경 500m 입시학원 수", tool_name="get_academy_demand",
                    metric_name="academy_count", value=42, unit="개"),
                _ev("stub:station", "인근 역 평일 18~22시 출구 통행량", tool_name="get_station_exit_traffic",
                    metric_name="exit_traffic", value=12480, unit="명"),
                _ev("stub:competitor", "반경 500m 스터디카페 수", tool_name="search_competitors",
                    metric_name="competitor_count", value=9, unit="개"),
            ],
            missing_data=[],
            confidence=0.7,
        ),
        AreaRecommendation(
            area_name="[stub] 상권 B",
            commercial_area_id="STUB-B",
            academy_demand_score=18.0,
            target_customer_score=15.0,
            station_traffic_score=11.0,
            activity_score=10.0,
            rent_score=11.0,
            competition_score=5.0,
            total_score=70.0,
            strengths=[
                "[stub] 평균 월세가 예산 대비 여유가 있어 임대료 점수가 높음",
                "[stub] 반경 500m 스터디카페가 4곳으로 경쟁 밀도가 낮은 편",
            ],
            risks=[
                "[stub] 학원 수가 상권 A보다 적어 유입 규모가 작을 수 있음",
                "[stub] 역과의 거리가 멀어 통행량 점수가 상대적으로 낮음",
            ],
            evidence=[
                _ev("stub:academy", "반경 500m 입시학원 수", tool_name="get_academy_demand",
                    metric_name="academy_count", value=27, unit="개"),
                _ev("stub:rent", "상권 평균 월세", tool_name="get_rent_and_closure_data",
                    metric_name="avg_monthly_rent", value=2_650_000, unit="원"),
                _ev("stub:competitor", "반경 500m 스터디카페 수", tool_name="search_competitors",
                    metric_name="competitor_count", value=4, unit="개"),
            ],
            missing_data=[],
            confidence=0.6,
        ),
    ]
    return StudySpotResponse(
        status="success",
        recommendations=recs,
        message="[stub] Agent 미연결 상태의 화면 확인용 응답입니다.",
    )


def _stub_partial_success() -> StudySpotResponse:
    """INT-05: 일부 세부 점수 None + Mock 혼합."""
    recs = [
        AreaRecommendation(
            area_name="[stub] 상권 C",
            commercial_area_id="STUB-C",
            academy_demand_score=20.0,
            target_customer_score=None,   # 누락 → 총점 기여 0점
            station_traffic_score=13.0,
            activity_score=9.0,
            rent_score=None,              # 누락 → 총점 기여 0점
            competition_score=6.0,
            total_score=48.0,
            strengths=[
                "[stub] 반경 500m 입시학원 38곳으로 학원 수요 점수가 25점 중 20점",
                "[stub] 인근 역 저녁 시간대 통행량이 입력한 운영 시간과 겹침",
            ],
            risks=[
                "[stub] 임대료 조회가 시간 초과(API_TIMEOUT)로 실패해 예산 적합성을 확인하지 못함",
                "[stub] 타깃 연령 구성 데이터가 없어(NO_DATA) 다른 후보와 직접 비교가 어려움",
                "[stub] 두 항목이 빠진 채 계산된 총점이라 점수를 그대로 믿기 어려움",
            ],
            evidence=[
                _ev("stub:academy", "반경 500m 입시학원 수", tool_name="get_academy_demand",
                    metric_name="academy_count", value=38, unit="개"),
                _ev("stub:station", "인근 역 평일 18~22시 출구 통행량", tool_name="get_station_exit_traffic",
                    metric_name="exit_traffic", value=9_310, unit="명"),
            ],
            missing_data=["target_customer_score: NO_DATA", "rent_score: API_TIMEOUT"],
            confidence=0.4,
        )
    ]
    return StudySpotResponse(
        status="success",
        recommendations=recs,
        message="[stub] 일부 지표 누락·Mock 혼합 화면 확인용 응답입니다.",
    )


def _stub_need_more(missing: list[str]) -> StudySpotResponse:
    return StudySpotResponse(
        status="need_more_information",
        recommendations=[],
        message="[stub] 분석에 필요한 조건이 부족합니다. 아래 항목을 입력해 주세요.",
        missing_required_inputs=missing,
    )


def _stub_no_result() -> StudySpotResponse:
    return StudySpotResponse(
        status="no_result",
        recommendations=[],
        message=(
            "[stub] 조건을 만족하는 검증 가능한 후보가 없습니다. "
            "예산 상한을 올리거나 지역 범위를 넓혀 보세요."
        ),
    )


def _stub_system_error() -> StudySpotResponse:
    return StudySpotResponse(
        status="no_result",
        recommendations=[],
        message="[stub] 시스템 오류로 분석을 완료하지 못했습니다. (error_code: API_TIMEOUT)",
    )


def _stub_approval_required(context: RuntimeContext) -> StudySpotResponse:
    action = PendingActionView(
        action_id=f"stub-{uuid.uuid4().hex[:8]}",
        action_type="send_report",
        payload_version=1,
        display_summary=(
            "[stub] 분석 보고서를 아래 대상에게 전송합니다.\n"
            "- 대상: example@stub.local\n"
            "- 내용: 추천 상권 2곳 요약\n"
            "※ Mock 구현이므로 승인해도 실제 전송되지 않습니다."
        ),
    )
    return StudySpotResponse(
        status="approval_required",
        recommendations=[],
        message="[stub] 아래 내용을 확인하고 승인 또는 거절해 주세요.",
        requires_approval=True,
        approval_action="send_report",
        pending_action=action,
    )


def _stub_after_decision(request: AgentRequest) -> StudySpotResponse:
    decision = request.approval_decision
    made = getattr(decision, "decision", None) or (
        decision.get("decision") if isinstance(decision, dict) else None
    )
    if made == "approve":
        msg = (
            "[stub] 승인 의도를 전달했습니다. 실제 행동은 Mock이므로 "
            "실제 전송/등록되지 않았습니다."
        )
    else:
        msg = "[stub] 거절 처리했습니다. 실행되지 않았습니다."
    return StudySpotResponse(status="no_result", recommendations=[], message=msg)
