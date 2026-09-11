"""StudySpot 공통 Pydantic 모델.

담당: 효주 · feature/scoring
명세: docs/00_공통계약.md

공통 모델은 이 파일에서 한 번만 선언하고 다른 모듈은 import만 한다.
모델 변경이 필요하면 Github Issue나 Slack으로 요청한다.

1차 선언 (데이터 조회 Tool 계약):
- ToolResult, AreaIdentity, AnalysisPeriod, MetricObservation,
  AcademyDemandData, NearbyStation, StationTrafficData

2차 선언 (입력·점수·응답·승인·State):
- BusinessConditions, RuntimeContext, UserPreferences
- ScoringInput, MarketScore
- EvidenceItem, AreaRecommendation, ActionResult, StudySpotResponse
- ApprovalDecision, AgentRequest, PendingAction, PendingActionView
- StudySpotState (LangChain create_agent용 TypedDict)

ToolResult.data에는 모델 인스턴스가 아니라 직렬화 결과를 넣는다.
    사전 결과: ToolResult(..., data=payload.model_dump(mode="json"))
    목록 결과: ToolResult(..., data=[item.model_dump(mode="json") for item in items])
"""

import math
import re
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, Literal

from langchain.agents import AgentState
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import NotRequired

__all__ = [
    # 상수·타입
    "ErrorCode",
    "DayType",
    "DIMENSION_KEYS",
    "SCORE_MAX_POINTS",
    "ScoreName",
    "ConditionField",
    "REQUIRED_CONDITION_FIELDS",
    "ActionType",
    "ApprovalAction",
    "ResponseStatus",
    "ActionStatus",
    "PendingActionStatus",
    "PENDING_ACTION_TRANSITIONS",
    # 1차
    "ToolResult",
    "AreaIdentity",
    "AnalysisPeriod",
    "MetricObservation",
    "AcademyDemandData",
    "NearbyStation",
    "StationTrafficData",
    # 2차
    "BusinessConditions",
    "RuntimeContext",
    "UserPreferences",
    "ScoringInput",
    "MarketScore",
    "EvidenceItem",
    "AreaRecommendation",
    "ActionResult",
    "StudySpotResponse",
    "ApprovalDecision",
    "AgentRequest",
    "PendingAction",
    "PendingActionView",
    "StudySpotState",
    "STATE_CHECKPOINT_TYPES",
]


# ---------------------------------------------------------------------------
# 공통 타입
# ---------------------------------------------------------------------------

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""공백만 있는 값을 허용하지 않는 문자열."""

Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""지역·상권·역 코드. 앞자리 0을 보존하기 위해 문자열만 허용한다 (숫자 입력은 거부)."""

Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]

_HHMM = r"([01]\d|2[0-3]):[0-5]\d"
TimeHHMM = Annotated[str, StringConstraints(pattern=rf"^{_HHMM}$")]
"""24시간제 'HH:MM' 시각."""

BudgetKRW = Annotated[int, Field(ge=0)]
"""원(KRW) 단위 금액. 화면에서 만원으로 받으면 ×10,000 해서 넘긴다."""

DayType = Literal["weekday", "weekend", "holiday"]

DIMENSION_KEYS: frozenset[str] = frozenset({"exit_number", "day_type", "time_slot"})
"""MetricObservation.dimensions에 쓸 수 있는 key. 새 key는 Github Issue나 Slack으로 요청하시면 추가하겠습니다.

| key         | 값 형식                                  | 예시            |
|-------------|------------------------------------------|-----------------|
| exit_number | 출구 번호 문자열                         | "3", "3-1"      |
| day_type    | period.day_types에 포함된 DayType 값     | "weekday"       |
| time_slot   | "HH:MM-HH:MM" (자정 통과 허용, 시작≠종료) | "18:00-22:00"   |
"""

_TIME_SLOT_PATTERN = re.compile(rf"^({_HHMM})-({_HHMM})$")

SCORE_MAX_POINTS = MappingProxyType(
    {
        "academy_demand_score": 25,
        "target_customer_score": 20,
        "station_traffic_score": 15,
        "activity_score": 15,
        "rent_score": 15,
        "competition_score": 10,
    }
)
"""고정 배점 (팀 결정). 사용자 우선순위와 관계없이 바꾸지 않는다."""

ScoreName = Literal[
    "academy_demand_score",
    "target_customer_score",
    "station_traffic_score",
    "activity_score",
    "rent_score",
    "competition_score",
]

ConditionField = Literal[
    "preferred_region",
    "deposit_budget",
    "monthly_rent_budget",
    "target_age",
    "operating_start_time",
    "operating_end_time",
]
REQUIRED_CONDITION_FIELDS: tuple[ConditionField, ...] = (
    "preferred_region",
    "deposit_budget",
    "monthly_rent_budget",
    "target_age",
    "operating_start_time",
    "operating_end_time",
)
"""분석 전에 반드시 받아야 하는 창업 조건."""

ActionType = Literal["send_report", "create_site_visit"]
ApprovalAction = Literal["none", "send_report", "create_site_visit"]
ResponseStatus = Literal["success", "need_more_information", "no_result", "approval_required"]
ActionStatus = Literal["executed", "failed", "rejected", "unknown", "simulated"]
PendingActionStatus = Literal["pending", "approved", "rejected", "executed", "failed", "unknown", "simulated"]

PENDING_ACTION_TRANSITIONS = MappingProxyType(
    {
        "pending": frozenset({"approved", "rejected"}),
        "approved": frozenset({"executed", "failed", "unknown", "simulated"}),
        "rejected": frozenset(),
        "executed": frozenset(),
        "failed": frozenset(),
        "unknown": frozenset(),
        "simulated": frozenset(),
    }
)
"""승인 대기 작업의 허용 상태 전이. 승인 없이 실행 상태로 갈 수 없고, 종료 상태 이후에는 바뀌지 않는다 (중복 실행 방지).

- unknown: 실행했지만 성공 여부를 확인하지 못함
- simulated: Mock으로 시연만 함, 실제 외부 행동 없음
"""


def _score(name: ScoreName) -> Any:
    """세부 점수 타입: 0 이상 해당 항목 배점 이하."""
    return Annotated[float, Field(ge=0, le=SCORE_MAX_POINTS[name], allow_inf_nan=False)]


def _has_duplicates(values: list[Any]) -> bool:
    return len(set(values)) != len(values)


def _require_observations_or_missing(payload: Any) -> None:
    if not payload.observations and not payload.missing_data:
        raise ValueError("observations와 missing_data가 모두 비어 있다 (데이터 없음은 missing_data에 사유 기록)")


class ErrorCode(StrEnum):
    """공통 오류 코드. 새 오류 코드는 Github Issue나 Slack으로 요청하시면 추가하겠습니다."""

    API_TIMEOUT = "API_TIMEOUT"
    API_AUTH_ERROR = "API_AUTH_ERROR"
    API_RATE_LIMIT = "API_RATE_LIMIT"
    API_BAD_REQUEST = "API_BAD_REQUEST"
    API_RESPONSE_ERROR = "API_RESPONSE_ERROR"
    AREA_NOT_FOUND = "AREA_NOT_FOUND"
    UNSUPPORTED_AREA = "UNSUPPORTED_AREA"
    STATION_NOT_FOUND = "STATION_NOT_FOUND"
    NO_DATA = "NO_DATA"
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED_INPUT = "MISSING_REQUIRED_INPUT"
    TOOL_INTERNAL_ERROR = "TOOL_INTERNAL_ERROR"
    MAX_ITERATION_REACHED = "MAX_ITERATION_REACHED"


class StudySpotModel(BaseModel):
    """모든 공통 모델의 기반. 선언되지 않은 필드는 거부한다."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Tool 반환
# ---------------------------------------------------------------------------


class ToolResult(StudySpotModel):
    """모든 Tool의 공통 반환 형식.

    | 상황                  | success | is_mock | error_code          |
    |-----------------------|---------|---------|---------------------|
    | 실제 조회 성공        | True    | False   | None                |
    | API 실패 후 Mock 사용 | True    | True    | 원래 오류 코드 유지 |
    | 개발 Mock 모드        | True    | True    | None                |
    | 사용 가능한 결과 없음 | False   | False   | 필수, data는 빈 값  |
    """

    success: bool
    source: NonEmptyStr
    data: dict[str, Any] | list[Any]
    error_code: ErrorCode | None = None
    error_message: str | None = None
    is_mock: bool

    @model_validator(mode="after")
    def _check_result_combination(self) -> "ToolResult":
        if not self.success:
            if self.error_code is None:
                raise ValueError("success=False이면 error_code가 필요하다")
            if self.data:
                raise ValueError("success=False이면 data는 빈 {} 또는 []이어야 한다")
            if self.is_mock:
                raise ValueError("Mock을 확보했다면 success=True로 반환한다")
        elif self.error_code is not None and not self.is_mock:
            raise ValueError("success=True에서 error_code는 Mock Fallback(is_mock=True)일 때만 유지한다")
        if self.error_message is not None and self.error_code is None:
            raise ValueError("error_message는 error_code와 함께 사용한다")
        return self


# ---------------------------------------------------------------------------
# 식별자·기간
# ---------------------------------------------------------------------------


class AreaIdentity(StudySpotModel):
    """상권 식별 정보. 모르는 코드·좌표는 만들지 않고 None으로 둔다."""

    commercial_area_id: Code
    administrative_code: Code | None
    area_name: NonEmptyStr
    latitude: Latitude | None
    longitude: Longitude | None

    @model_validator(mode="after")
    def _check_coordinate_pair(self) -> "AreaIdentity":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude와 longitude는 함께 제공하거나 함께 None이어야 한다")
        return self


class AnalysisPeriod(StudySpotModel):
    """조회·분석 대상 기간.

    - 하루 전체를 보려면 start_time·end_time을 None으로 둔다.
    - 자정을 넘는 구간(예: 22:00~02:00)은 허용한다.
    - start_time == end_time은 24시간 여부가 미합의라 거부한다.
    """

    start_date: date
    end_date: date
    timezone: NonEmptyStr = "Asia/Seoul"
    day_types: list[DayType] = Field(min_length=1)
    start_time: TimeHHMM | None = None
    end_time: TimeHHMM | None = None

    @model_validator(mode="after")
    def _check_period(self) -> "AnalysisPeriod":
        if self.end_date < self.start_date:
            raise ValueError("end_date는 start_date보다 앞설 수 없다")
        if _has_duplicates(self.day_types):
            raise ValueError("day_types에 중복 값이 있다")
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("start_time과 end_time은 함께 제공하거나 함께 None이어야 한다")
        if self.start_time is not None and self.start_time == self.end_time:
            raise ValueError("start_time과 end_time이 같다 (24시간 표현은 미합의)")
        return self


# ---------------------------------------------------------------------------
# 관측값·데이터 Tool payload
# ---------------------------------------------------------------------------


class MetricObservation(StudySpotModel):
    """원천 지표 하나의 관측값.

    - 실제 0은 value=0.0, 데이터 없음은 value=None + missing_reason으로 구분한다.
    - dimensions: 출구·요일·시간대 등 세부 구분. key는 DIMENSION_KEYS만 사용한다.
      예: {"exit_number": "3", "day_type": "weekday", "time_slot": "18:00-22:00"}
    """

    metric_name: NonEmptyStr
    value: Annotated[float, Field(allow_inf_nan=False)] | None
    unit: NonEmptyStr
    period: AnalysisPeriod
    source: NonEmptyStr
    is_mock: bool
    missing_reason: NonEmptyStr | None = None
    dimensions: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_missing_reason(self) -> "MetricObservation":
        if self.value is None and self.missing_reason is None:
            raise ValueError("value=None이면 missing_reason이 필요하다")
        if self.value is not None and self.missing_reason is not None:
            raise ValueError("value가 있으면 missing_reason은 None이어야 한다")
        return self

    @model_validator(mode="after")
    def _check_dimensions(self) -> "MetricObservation":
        unknown = set(self.dimensions) - DIMENSION_KEYS
        if unknown:
            raise ValueError(f"등록되지 않은 dimensions key: {sorted(unknown)} (추가는 Github Issue나 Slack으로 요청)")

        day_type = self.dimensions.get("day_type")
        if day_type is not None and day_type not in self.period.day_types:
            raise ValueError(f"dimensions.day_type '{day_type}'이 period.day_types에 없다")

        time_slot = self.dimensions.get("time_slot")
        if time_slot is not None:
            match = _TIME_SLOT_PATTERN.match(time_slot)
            if match is None:
                raise ValueError("dimensions.time_slot은 'HH:MM-HH:MM' 형식이어야 한다")
            if match.group(1) == match.group(3):
                raise ValueError("dimensions.time_slot의 시작과 종료가 같다")
        return self


class AcademyDemandData(StudySpotModel):
    """get_academy_demand의 정상 data. 관측값 또는 누락 사유 중 하나 이상 필요 (학원 0개는 value=0 관측값)."""

    commercial_area_id: Code
    administrative_code: Code | None
    observations: list[MetricObservation] = Field(default_factory=list)
    missing_data: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_not_empty(self) -> "AcademyDemandData":
        _require_observations_or_missing(self)
        return self


class NearbyStation(StudySpotModel):
    """find_nearby_stations의 정상 data 목록 항목. station_id 코드 체계는 중우님이 문서화 예정입니다."""

    station_id: Code
    station_name: NonEmptyStr
    latitude: Latitude
    longitude: Longitude
    distance_m: float = Field(ge=0, allow_inf_nan=False)


class StationTrafficData(StudySpotModel):
    """get_station_exit_traffic의 정상 data.

    출구·요일·시간대 구분은 각 observation의 dimensions(exit_number, day_type, time_slot)에 담는다.
    집계 기준은 중우님이 고정·문서화 예정입니다.
    """

    station_id: Code
    observations: list[MetricObservation] = Field(default_factory=list)
    missing_data: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_not_empty(self) -> "StationTrafficData":
        _require_observations_or_missing(self)
        return self


# ---------------------------------------------------------------------------
# 사용자 입력·신원·선호
# ---------------------------------------------------------------------------


class BusinessConditions(StudySpotModel):
    """사용자의 창업 조건. 대화 중 일부만 받은 상태도 표현할 수 있도록 모든 값은 None을 허용한다.

    - 예산은 원(KRW) 단위 0 이상.
    - 운영 시간은 'HH:MM'. 자정 통과 허용. 시작=종료는 24시간 운영으로 해석한다 (제안, PR에서 확인).
      가게 운영 시간이라 AnalysisPeriod(데이터 조회 구간)와는 다른 개념이다. 조회 구간의 하루 전체는 시각을 None으로 둔다.
    - priority_metrics는 설명용이다. 고정 배점이라 점수에는 영향이 없다.
    """

    preferred_region: NonEmptyStr | None = None
    deposit_budget: BudgetKRW | None = None
    monthly_rent_budget: BudgetKRW | None = None
    target_age: NonEmptyStr | None = None
    operating_start_time: TimeHHMM | None = None
    operating_end_time: TimeHHMM | None = None
    priority_metrics: list[ScoreName] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_priority_metrics(self) -> "BusinessConditions":
        if _has_duplicates(self.priority_metrics):
            raise ValueError("priority_metrics에 중복 값이 있다")
        return self

    def missing_required_inputs(self) -> list[ConditionField]:
        """아직 받지 못한 필수 조건 이름 목록 (REQUIRED_CONDITION_FIELDS 순서)."""
        return [name for name in REQUIRED_CONDITION_FIELDS if getattr(self, name) is None]


class RuntimeContext(StudySpotModel):
    """실행 주체 정보. 신뢰 가능한 실행 계층에서 주입하며 사용자 입력·LLM이 지정하지 않는다. 생성 후 변경 불가."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: NonEmptyStr
    session_id: NonEmptyStr
    user_role: NonEmptyStr


class UserPreferences(StudySpotModel):
    """세션을 넘어 유지할 사용자 선호 (Store). 사용자의 명시적 요청·동의가 있을 때만 저장한다.

    공통계약의 target_customer는 BusinessConditions와 맞춰 target_age로 통일했다.
    shortlisted_areas는 관심 상권의 commercial_area_id 목록이다.
    """

    user_id: NonEmptyStr
    preferred_regions: list[NonEmptyStr] = Field(default_factory=list)
    deposit_budget: BudgetKRW | None = None
    monthly_rent_budget: BudgetKRW | None = None
    target_age: NonEmptyStr | None = None
    priority_metrics: list[ScoreName] = Field(default_factory=list)
    shortlisted_areas: list[Code] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_duplicates(self) -> "UserPreferences":
        for name in ("preferred_regions", "priority_metrics", "shortlisted_areas"):
            if _has_duplicates(getattr(self, name)):
                raise ValueError(f"{name}에 중복 값이 있다")
        return self


# ---------------------------------------------------------------------------
# 점수
# ---------------------------------------------------------------------------


class ScoringInput(StudySpotModel):
    """calculate_market_score의 입력. LLM이 아니라 Agent 코드가 State의 조회 결과로 조립한다.

    필수 창업 조건이 모두 있어야 한다 (부족하면 분석 Tool을 부르지 않는다는 공통계약 규칙).
    tool_results의 key는 Tool 이름을 기본으로 한다. 같은 Tool을 여러 번 호출할 때의 key 규칙은
    중우님과 확정 예정이다.
    """

    area: AreaIdentity
    conditions: BusinessConditions
    period: AnalysisPeriod
    tool_results: dict[NonEmptyStr, ToolResult] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_conditions_complete(self) -> "ScoringInput":
        missing = self.conditions.missing_required_inputs()
        if missing:
            raise ValueError(f"점수 계산에 필요한 조건이 없다: {missing}")
        return self


class _ScoreFields(StudySpotModel):
    """6개 세부 점수·총점·신뢰도의 공통 필드와 불변식.

    - 세부 점수는 0~배점. 계산 불가는 None이며 missing_data에 사유를 기록한다.
    - total_score = 세부 점수 합 (None은 0점으로 계산).
    - confidence는 0~1의 데이터 품질 지표이며 성공 확률이 아니다.
    """

    academy_demand_score: _score("academy_demand_score") | None
    target_customer_score: _score("target_customer_score") | None
    station_traffic_score: _score("station_traffic_score") | None
    activity_score: _score("activity_score") | None
    rent_score: _score("rent_score") | None
    competition_score: _score("competition_score") | None
    total_score: float = Field(ge=0, le=100, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    missing_data: list[NonEmptyStr] = Field(default_factory=list)

    def score_values(self) -> dict[ScoreName, float | None]:
        """세부 점수 이름 → 값 (None 포함)."""
        return {name: getattr(self, name) for name in SCORE_MAX_POINTS}

    @model_validator(mode="after")
    def _check_score_invariants(self) -> "_ScoreFields":
        scores = self.score_values()
        expected_total = sum(value for value in scores.values() if value is not None)
        if not math.isclose(self.total_score, expected_total, abs_tol=1e-6):
            raise ValueError(
                f"total_score({self.total_score})가 세부 점수 합({expected_total})과 다르다 (None은 0점)"
            )
        if any(value is None for value in scores.values()) and not self.missing_data:
            raise ValueError("None인 세부 점수가 있으면 missing_data에 누락 사유를 기록한다")
        if all(value is None for value in scores.values()) and self.confidence != 0:
            raise ValueError("전 항목이 누락되면 confidence는 0이어야 한다")
        return self


class MarketScore(_ScoreFields):
    """calculate_market_score의 정상 data. 전 항목 None도 표현할 수 있지만 추천 대상에서는 제외된다."""


class EvidenceItem(StudySpotModel):
    """추천 근거 한 건. Mock 데이터에서 온 근거는 is_mock=True로 표시한다.

    수치 근거는 tool_name·metric_name·value·unit을 함께 적어 Tool 결과와 대조할 수 있게 한다.
    정성적 근거(예: 조사 기준 시점)는 이 필드들을 비워도 된다.
    """

    source: NonEmptyStr
    summary: NonEmptyStr
    is_mock: bool
    tool_name: NonEmptyStr | None = None
    metric_name: NonEmptyStr | None = None
    value: Annotated[float, Field(allow_inf_nan=False)] | None = None
    unit: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check_numeric_evidence(self) -> "EvidenceItem":
        if self.value is not None and None in (self.tool_name, self.metric_name, self.unit):
            raise ValueError("수치 근거(value)는 tool_name·metric_name·unit과 함께 적는다")
        return self


class AreaRecommendation(_ScoreFields):
    """추천 상권 하나. 역할 5가 MarketScore와 근거로 조립한다.

    - commercial_area_id: 상권 구분용으로 공통계약에 추가했다.
    - 전 항목 None인 후보는 추천할 수 없다.
    - 일부 항목이 None이면 비교 한계를 risks에 적는다.
    - 근거(evidence)는 1개 이상.
    """

    commercial_area_id: Code
    area_name: NonEmptyStr
    strengths: list[NonEmptyStr] = Field(default_factory=list)
    risks: list[NonEmptyStr] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_recommendable(self) -> "AreaRecommendation":
        scores = self.score_values().values()
        if all(value is None for value in scores):
            raise ValueError("전 항목이 누락된 후보는 추천할 수 없다")
        if any(value is None for value in scores) and not self.risks:
            raise ValueError("일부 점수가 누락되면 비교 한계를 risks에 적는다")
        return self


# ---------------------------------------------------------------------------
# 외부 행동·최종 응답
# ---------------------------------------------------------------------------


class PendingActionView(StudySpotModel):
    """승인 화면에 보여줄 승인 대기 작업 (공개용). user_id·session_id·실행 payload는 넣지 않는다.

    UI는 승인/거절할 때 action_id·payload_version을 ApprovalDecision에 그대로 담아 보낸다.
    """

    action_id: NonEmptyStr
    action_type: ActionType
    payload_version: int = Field(ge=1)
    display_summary: NonEmptyStr


class ActionResult(StudySpotModel):
    """보고서 전송·현장답사 일정 등록의 실행 결과.

    | status    | 의미                                   | is_mock |
    |-----------|----------------------------------------|---------|
    | executed  | 실제로 실행됨                          | False   |
    | simulated | Mock으로 시연만 함, 실제 외부 행동 없음 | True    |
    | failed    | 실행 시도 후 실패                      | 무관    |
    | rejected  | 사용자가 거절해 실행하지 않음          | 무관    |
    | unknown   | 실행했지만 성공 여부를 확인하지 못함   | 무관    |
    """

    action_id: NonEmptyStr
    action_type: ActionType
    status: ActionStatus
    message: NonEmptyStr
    is_mock: bool

    @model_validator(mode="after")
    def _check_mock_status(self) -> "ActionResult":
        if self.status == "executed" and self.is_mock:
            raise ValueError("Mock은 실제 실행(executed)으로 표시하지 않는다. simulated를 사용한다")
        if self.status == "simulated" and not self.is_mock:
            raise ValueError("simulated는 Mock(is_mock=True)일 때만 사용한다")
        return self


class StudySpotResponse(StudySpotModel):
    """Agent의 최종 응답 (UI로 전달).

    | status                | 조건                                                        |
    |-----------------------|-------------------------------------------------------------|
    | success               | 추천 1~3개, 또는 추천 0개 + action_result                  |
    | need_more_information | missing_required_inputs 1개 이상, 추천 0개                  |
    | no_result             | 추천 0개                                                    |
    | approval_required     | requires_approval=True, 승인 대상, pending_action 필수, action_result 금지 |

    approval_required가 아니면 requires_approval=False, approval_action="none", pending_action=None.
    """

    status: ResponseStatus
    recommendations: list[AreaRecommendation] = Field(default_factory=list, max_length=3)
    message: NonEmptyStr
    missing_required_inputs: list[ConditionField] = Field(default_factory=list)
    requires_approval: bool = False
    approval_action: ApprovalAction = "none"
    pending_action: PendingActionView | None = None
    action_result: ActionResult | None = None

    @model_validator(mode="after")
    def _check_status_combination(self) -> "StudySpotResponse":
        count = len(self.recommendations)
        area_ids = [rec.commercial_area_id for rec in self.recommendations]
        if _has_duplicates(area_ids):
            raise ValueError("같은 상권이 추천 목록에 중복되었다")
        if _has_duplicates(self.missing_required_inputs):
            raise ValueError("missing_required_inputs에 중복 값이 있다")

        if self.status == "success":
            if count == 0 and self.action_result is None:
                raise ValueError("success는 추천 1~3개 또는 action_result가 필요하다")
        elif self.status == "need_more_information":
            if not self.missing_required_inputs:
                raise ValueError("need_more_information은 missing_required_inputs가 필요하다")
            if count:
                raise ValueError("need_more_information에서는 추천을 반환하지 않는다")
        elif self.status == "no_result":
            if count:
                raise ValueError("no_result에서는 추천을 반환하지 않는다")

        if self.status != "need_more_information" and self.missing_required_inputs:
            raise ValueError("missing_required_inputs는 need_more_information에서만 사용한다")

        if self.status == "approval_required":
            if not self.requires_approval or self.approval_action == "none" or self.pending_action is None:
                raise ValueError("approval_required는 requires_approval=True, 승인 대상, pending_action이 필요하다")
            if self.pending_action.action_type != self.approval_action:
                raise ValueError("approval_action과 pending_action.action_type이 다르다")
            if self.action_result is not None:
                raise ValueError("승인 대기 중에는 action_result를 반환하지 않는다")
        elif self.requires_approval or self.approval_action != "none" or self.pending_action is not None:
            raise ValueError(
                "승인 대기가 아니면 requires_approval=False, approval_action='none', pending_action=None이어야 한다"
            )
        return self


# ---------------------------------------------------------------------------
# UI → Agent 요청·승인
# ---------------------------------------------------------------------------


class ApprovalDecision(StudySpotModel):
    """사용자의 승인/거절. 응답의 pending_action에 있던 action_id·payload_version을 그대로 보낸다."""

    decision: Literal["approve", "reject"]
    action_id: NonEmptyStr
    payload_version: int = Field(ge=1)


class AgentRequest(StudySpotModel):
    """run_analysis의 UI 입력. UI는 State 전체를 보내거나 수정하지 않는다.

    - message: 이번에 사용자가 입력한 메시지 1개 (석휘님 결정). 대화 이력은 checkpointer가 보관하므로
      UI가 과거 대화를 다시 보내지 않는다.
    - message 또는 approval_decision 중 하나 이상이 있어야 한다.
    - 조건 변경은 기존 승인을 무효화하므로 approval_decision과 business_conditions를 함께 보낼 수 없다.
    """

    message: NonEmptyStr | None = None
    business_conditions: BusinessConditions | None = None
    approval_decision: ApprovalDecision | None = None

    @model_validator(mode="after")
    def _check_request(self) -> "AgentRequest":
        if self.message is None and self.approval_decision is None:
            raise ValueError("message 또는 approval_decision이 필요하다")
        if self.approval_decision is not None and self.business_conditions is not None:
            raise ValueError("승인 결정과 조건 변경은 한 요청에 함께 보낼 수 없다")
        return self


class PendingAction(StudySpotModel):
    """승인 대기 중인 외부 행동 (서버 측 보관).

    - 실행 payload는 서버에 따로 보관하고, 사용자에게는 to_view()로 공개용 정보만 보여준다.
    - 내용이 바뀌면 payload_version을 올린다. 승인한 사용자·세션·버전이 다르면 실행하지 않는다.
    - 생성 후 직접 수정할 수 없다. 상태는 transition_to()로만 바꾸고 model_copy(update=...)로 바꾸지 않는다.
    - 모델만으로 우회를 완전히 막을 수는 없으므로, 실행 직전에 저장된 상태가 approved인지
      실행 계층(middleware)에서 다시 확인한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: NonEmptyStr
    action_type: ActionType
    payload_version: int = Field(ge=1)
    display_summary: NonEmptyStr
    status: PendingActionStatus = "pending"
    user_id: NonEmptyStr
    session_id: NonEmptyStr

    def can_transition_to(self, new_status: PendingActionStatus) -> bool:
        """현재 상태에서 new_status로 바꿀 수 있는지."""
        return new_status in PENDING_ACTION_TRANSITIONS[self.status]

    def transition_to(self, new_status: PendingActionStatus) -> "PendingAction":
        """허용된 전이면 새 상태의 PendingAction을 돌려주고, 아니면 ValueError를 낸다. 원래 객체는 바뀌지 않는다."""
        if not self.can_transition_to(new_status):
            raise ValueError(f"허용되지 않는 상태 전이: {self.status} → {new_status}")
        return self.model_copy(update={"status": new_status})

    def to_view(self) -> PendingActionView:
        """승인 화면용 공개 정보."""
        return PendingActionView(
            action_id=self.action_id,
            action_type=self.action_type,
            payload_version=self.payload_version,
            display_summary=self.display_summary,
        )


# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------


class StudySpotState(AgentState):
    """create_agent(state_schema=StudySpotState)에 넣는 Agent State.

    LangChain 1.3.x의 create_agent는 AgentState를 확장한 TypedDict를 요구한다.
    messages는 AgentState가 제공한다. 값의 의미·수명은 소유님 설계, 갱신 구현은 memory/state.py.

    조건 변경 시 초기화 (소유님 결정, 1차 통합 기준):
    - 예산·운영시간·타깃 연령 변경 → current_candidates, tool_results, market_scores,
      missing_data, pending_action 초기화
    - 희망 지역 변경 → 위 항목 + searched_areas 초기화
    - priority_metrics만 변경 → 재조회·재계산 없음 (설명에만 반영)
    """

    business_conditions: NotRequired[BusinessConditions | None]
    searched_areas: NotRequired[list[AreaIdentity]]
    current_candidates: NotRequired[list[AreaIdentity]]
    tool_results: NotRequired[dict[str, ToolResult]]
    """호출 ID → ToolResult"""
    market_scores: NotRequired[dict[str, MarketScore]]
    """commercial_area_id → MarketScore"""
    missing_data: NotRequired[list[str]]
    pending_action: NotRequired[PendingAction | None]


STATE_CHECKPOINT_TYPES: tuple[tuple[str, str], ...] = tuple(
    (__name__, name)
    for name in ("BusinessConditions", "AreaIdentity", "ToolResult", "ErrorCode", "MarketScore", "PendingAction")
)
"""StudySpotState에 저장되는 모델 목록. checkpointer가 경고 없이 복원하도록 허용 목록에 넣는다.

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_CHECKPOINT_TYPES))
"""
