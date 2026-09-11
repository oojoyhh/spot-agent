"""공통 모델 어댑터.

담당: 역할 6 · 명하 · feature/ui
명세: docs/00_공통계약.md 3~5절, docs/06_Streamlit_Integration.md

역할 4(효주)의 `models/schemas.py`가 아직 비어 있어 UI 개발을 시작할 수 없으므로,
이 모듈이 import 경계를 한 곳으로 모은다.

- `models.schemas`에 모델이 선언돼 있으면 그것을 그대로 재노출한다(SCHEMAS_SOURCE="models.schemas").
- 없으면 공통계약 3~5절의 선언 명세만 옮겨 적은 **임시 미러**를 사용한다
  (SCHEMAS_SOURCE="ui.contracts(mirror)").

임시 미러는 화면 개발용이며 공통 모델의 원본이 아니다. 역할 4의 선언 PR이 merge되면
이 파일의 미러 블록은 통째로 삭제하고 재노출만 남긴다. 미러에 필드를 임의로 추가하지 않는다.
필드가 더 필요하면 역할 4·5에게 계약 확장을 요청한다(아래 CONTRACT-GAP 주석 참고).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

SCHEMAS_SOURCE: str

try:  # pragma: no cover - 역할 4 선언 PR merge 후 이 경로만 남는다
    from models.schemas import (  # type: ignore[attr-defined]  # noqa: F401
        AgentRequest,
        ApprovalDecision,
        AreaRecommendation,
        BusinessConditions,
        EvidenceItem,
        MarketScore,
        PendingActionView,
        RuntimeContext,
        StudySpotResponse,
        ToolResult,
    )

    SCHEMAS_SOURCE = "models.schemas"
    USING_MIRROR = False

except ImportError:  # 임시 미러 -------------------------------------------------
    from pydantic import BaseModel, Field, model_validator

    SCHEMAS_SOURCE = "ui.contracts(mirror)"
    USING_MIRROR = True

    class ToolResult(BaseModel):
        """공통계약 3절. UI는 직접 만들지 않고 표시용으로만 받는다."""

        success: bool
        source: str
        data: dict[str, Any] | list[Any] = Field(default_factory=dict)
        error_code: Optional[str] = None
        error_message: Optional[str] = None
        is_mock: bool = False

    class BusinessConditions(BaseModel):
        """화면 입력 필드와 1:1로 대응한다. 빈 값은 None, 실제 0은 0으로 구분한다."""

        preferred_region: Optional[str] = None
        deposit_budget: Optional[int] = None       # 단위: 원(KRW)
        monthly_rent_budget: Optional[int] = None  # 단위: 원(KRW)
        target_age: Optional[str] = None
        operating_start_time: Optional[str] = None  # "HH:MM"
        operating_end_time: Optional[str] = None    # "HH:MM"
        priority_metrics: list[str] = Field(default_factory=list)

    class RuntimeContext(BaseModel):
        """신뢰 가능한 실행 계층에서 주입한다.

        사용자 입력이나 LLM이 user_id·user_role을 지정하는 화면을 만들지 않는다.
        """

        user_id: str
        session_id: str
        user_role: str

    class EvidenceItem(BaseModel):
        source: str
        summary: str
        is_mock: bool = False
        # 2차 공통 모델에서 추가된 수치 근거 필드.
        # 값이 있으면 화면에 "값 단위 (지표명)"으로 같이 보여 준다.
        tool_name: Optional[str] = None
        metric_name: Optional[str] = None
        value: Optional[float] = None
        unit: Optional[str] = None

    class MarketScore(BaseModel):
        academy_demand_score: Optional[float] = None   # 최대 25
        target_customer_score: Optional[float] = None  # 최대 20
        station_traffic_score: Optional[float] = None  # 최대 15
        activity_score: Optional[float] = None         # 최대 15
        rent_score: Optional[float] = None             # 최대 15
        competition_score: Optional[float] = None      # 최대 10
        total_score: float
        confidence: float
        missing_data: list[str] = Field(default_factory=list)

    class AreaRecommendation(BaseModel):
        area_name: str
        # CONTRACT-GAP: docs/06 "추가 제안" — 관심 상권 선택·중복 식별을 위해
        # commercial_area_id가 필요하다. 역할 4·5 확정 전까지 Optional로 두고,
        # 값이 없으면 UI는 이름 문자열을 식별자로 저장하지 않는다.
        commercial_area_id: Optional[str] = None
        academy_demand_score: Optional[float] = None
        target_customer_score: Optional[float] = None
        station_traffic_score: Optional[float] = None
        activity_score: Optional[float] = None
        rent_score: Optional[float] = None
        competition_score: Optional[float] = None
        total_score: float
        strengths: list[str] = Field(default_factory=list)
        risks: list[str] = Field(default_factory=list)
        evidence: list[EvidenceItem] = Field(default_factory=list)
        missing_data: list[str] = Field(default_factory=list)
        confidence: float

    class PendingActionView(BaseModel):
        """승인 화면에 노출해도 되는 공개용 승인 정보."""

        action_id: str
        action_type: Literal["send_report", "create_site_visit"]
        payload_version: int
        display_summary: str

    class StudySpotResponse(BaseModel):
        status: Literal[
            "success", "need_more_information", "no_result", "approval_required"
        ]
        recommendations: list[AreaRecommendation] = Field(default_factory=list)
        message: str = ""
        missing_required_inputs: list[str] = Field(default_factory=list)
        requires_approval: bool = False
        approval_action: Literal["none", "send_report", "create_site_visit"] = "none"
        # CONTRACT-GAP: 공통계약 3절 StudySpotResponse 표에는 pending_action이 없는데,
        # docs/06은 "승인 버튼은 action_id·payload 버전에 묶인 의도만 보낸다"를 요구한다.
        # UI가 action_id를 만들어낼 수 없으므로 Optional 필드로 두고, 값이 없으면
        # 승인 버튼을 비활성화한다(가짜 식별자 생성 금지). 역할 4·5 확정 필요.
        pending_action: Optional[PendingActionView] = None

    class ApprovalDecision(BaseModel):
        decision: Literal["approve", "reject"]
        action_id: str
        payload_version: int

    class AgentRequest(BaseModel):
        """UI → Agent 경계 입력. State 전체를 전달하거나 수정하지 않는다."""

        message: Optional[str] = None
        business_conditions: Optional[BusinessConditions] = None
        approval_decision: Optional[ApprovalDecision] = None

        @model_validator(mode="after")
        def _check_request(self) -> "AgentRequest":
            if self.message is None and self.approval_decision is None:
                raise ValueError("message 또는 approval_decision이 필요하다")
            if self.approval_decision is not None and self.business_conditions is not None:
                raise ValueError("승인 결정과 조건 변경은 한 요청에 함께 보낼 수 없다")
            return self


# --- 화면 표시용 상수 (모델이 아니라 UI 라벨) --------------------------------

#: (필드명, 화면 라벨, 최대점) — 공통계약 5절 고정 배점. UI는 배점을 바꾸지 않는다.
SCORE_FIELDS: tuple[tuple[str, str, int], ...] = (
    ("academy_demand_score", "학원 수요", 25),
    ("target_customer_score", "타깃 고객 적합도", 20),
    ("station_traffic_score", "지하철 이용객", 15),
    ("activity_score", "활동성", 15),
    ("rent_score", "임대료", 15),
    ("competition_score", "경쟁 강도", 10),
)

#: 누락 세부 점수 표기. 실제 관측 0점과 섞어 쓰지 않는다(docs/06).
MISSING_SCORE_LABEL = "데이터 없음 (총점에는 0점 반영)"

#: 타깃 연령 선택지 (효주님과 협의).
#: 역할 1이 학원 API의 '학년'과 지하철 API의 '나이대' 코드로 변환한다.
#: 자유 입력은 API 코드로 매핑할 수 없어 선택형으로 고정한다.
TARGET_AGE_OPTIONS: tuple[str, ...] = (
    "중학생",
    "고등학생",
    "대학생",
    "20대",
    "30대 이상",
    "전체",
)

#: 선택 안 함 = 미입력(None). 필수 조건이라 need_more_information으로 이어진다.
TARGET_AGE_UNSET_LABEL = "(선택 안 함)"

#: 필수 조건 필드 → 화면 라벨. need_more_information 안내에 사용한다.
REQUIRED_FIELD_LABELS: dict[str, str] = {
    "preferred_region": "희망 지역",
    "deposit_budget": "보증금 예산",
    "monthly_rent_budget": "월세 예산",
    "target_age": "타깃 연령",
    "operating_start_time": "운영 시작 시간",
    "operating_end_time": "운영 종료 시간",
}

PRIORITY_METRIC_LABELS: dict[str, str] = {
    field: label
    for field, label, _ in SCORE_FIELDS
}

PRIORITY_METRIC_OPTIONS: tuple[str, ...] = tuple(
    PRIORITY_METRIC_LABELS
)

APPROVAL_ACTION_LABELS: dict[str, str] = {
    "none": "없음",
    "send_report": "분석 보고서 전송",
    "create_site_visit": "현장답사 일정 등록",
}

__all__ = [
    "SCHEMAS_SOURCE",
    "USING_MIRROR",
    "ToolResult",
    "BusinessConditions",
    "RuntimeContext",
    "EvidenceItem",
    "MarketScore",
    "AreaRecommendation",
    "PendingActionView",
    "ApprovalDecision",
    "StudySpotResponse",
    "AgentRequest",
    "SCORE_FIELDS",
    "MISSING_SCORE_LABEL",
    "TARGET_AGE_OPTIONS",        # ← 추가
    "TARGET_AGE_UNSET_LABEL",    # ← 추가
    "REQUIRED_FIELD_LABELS",
    "PRIORITY_METRIC_OPTIONS",
    "APPROVAL_ACTION_LABELS",
]
