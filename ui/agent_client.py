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

import uuid
from typing import Any

from ui.contracts import (
    AgentRequest,
    AreaRecommendation,
    BusinessConditions,
    EvidenceItem,
    PendingAction,
    RuntimeContext,
    StudySpotResponse,
)

try:  # pragma: no cover - 역할 5 PR merge 후 이 경로만 남는다
    from agent.main_agent import run_analysis as _run_analysis  # type: ignore

    BACKEND = "agent.main_agent"
except ImportError:
    _run_analysis = None
    BACKEND = "stub"

AGENT_CONNECTED = BACKEND != "stub"

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
    if scenario.startswith("success (일부"):
        return _stub_partial_success()
    if scenario == "success":
        return _stub_success()
    if scenario == "need_more_information":
        return _stub_need_more(["monthly_rent_budget", "operating_end_time"])
    if scenario == "no_result":
        return _stub_no_result()
    if scenario.startswith("no_result (시스템"):
        return _stub_system_error()
    if scenario == "approval_required":
        return _stub_approval_required(context)

    # 승인 요청은 business_conditions 검사보다 먼저 처리
    if request.approval_decision is not None:
        return _stub_after_decision(request)

    conditions = request.business_conditions or BusinessConditions()

    # 자동 모드: 필수 조건이 빠졌으면 데이터 Tool을 호출하지 않고 되묻는다(INT-02).
    missing = _missing_required(request.business_conditions)
    if missing:
        return _stub_need_more(missing)
    if request.approval_decision is not None:
        return _stub_after_decision(request)
    return _stub_partial_success()


def _ev(source: str, summary: str, is_mock: bool = True) -> Any:
    return EvidenceItem(source=source, summary=summary, is_mock=is_mock)


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
            strengths=["[stub] 장점 표시 자리"],
            risks=["[stub] 위험요인 표시 자리"],
            evidence=[_ev("stub", "실제 조회 아님. 화면 확인용 값")],
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
            strengths=["[stub] 장점 표시 자리"],
            risks=["[stub] 위험요인 표시 자리"],
            evidence=[_ev("stub", "실제 조회 아님. 화면 확인용 값")],
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
            strengths=["[stub] 장점 표시 자리"],
            risks=["[stub] 일부 지표 누락으로 비교 한계 있음"],
            evidence=[
                _ev("stub:academy", "학원 수요 Mock 값", is_mock=True),
                _ev("stub:station", "지하철 이용객 Mock 값", is_mock=True),
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
    action = PendingAction(
        action_id=f"stub-{uuid.uuid4().hex[:8]}",
        action_type="send_report",
        payload_version="v1",
        display_summary=(
            "[stub] 분석 보고서를 아래 대상에게 전송합니다.\n"
            "- 대상: example@stub.local\n"
            "- 내용: 추천 상권 2곳 요약\n"
            "※ Mock 구현이므로 승인해도 실제 전송되지 않습니다."
        ),
        status="pending",
        user_id=context.user_id,
        session_id=context.session_id,
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
