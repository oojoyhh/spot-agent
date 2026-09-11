"""StudySpot 공통 Pydantic 모델.

담당: 효주 · feature/scoring
명세: docs/00_공통계약.md

공통 모델은 이 파일에서 한 번만 선언하고 다른 모듈은 import만 한다.
모델 변경이 필요하면 Github Issue나 Slack으로 요청한다.

1차 선언 범위 (데이터 조회 Tool 계약):
- ToolResult, AreaIdentity, AnalysisPeriod, MetricObservation,
  AcademyDemandData, NearbyStation, StationTrafficData

다음 PR에서 추가 예정:
- BusinessConditions, RuntimeContext, UserPreferences, StudySpotState,
  MarketScore, EvidenceItem, AreaRecommendation, StudySpotResponse,
  ScoringInput, AgentRequest, PendingAction

ToolResult.data에는 모델 인스턴스가 아니라 직렬화 결과를 넣는다.
    사전 결과: ToolResult(..., data=payload.model_dump(mode="json"))
    목록 결과: ToolResult(..., data=[item.model_dump(mode="json") for item in items])
"""

import re
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

__all__ = [
    "ErrorCode",
    "DayType",
    "DIMENSION_KEYS",
    "ToolResult",
    "AreaIdentity",
    "AnalysisPeriod",
    "MetricObservation",
    "AcademyDemandData",
    "NearbyStation",
    "StationTrafficData",
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
        if len(set(self.day_types)) != len(self.day_types):
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
    """get_academy_demand의 정상 data."""

    commercial_area_id: Code
    administrative_code: Code | None
    observations: list[MetricObservation] = Field(default_factory=list)
    missing_data: list[NonEmptyStr] = Field(default_factory=list)


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
