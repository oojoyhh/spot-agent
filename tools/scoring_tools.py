"""입지점수 계산 Tool.

담당: 역할 4 · 효주 · feature/scoring
명세: docs/04_Scoring_Structured_Output.md · 산식: docs/scoring.md

- calculate_market_score(scoring_input) -> ToolResult (정상 data: MarketScore 직렬화 사전)
- 고정 배점: 학원 25 · 타깃 20 · 지하철 15 · 운영시간 유동성 15 · 임대 15 · 경쟁 10
- 점수는 이 모듈만 계산한다. LLM이 점수를 만들거나 고치지 않는다
- 누락 원천값을 0으로 대체하지 않는다. Mock 사용 시 is_mock=True를 전파한다

Agent 연결 (석휘님):
- ScoringInput.tool_results의 key는 Tool 이름이다 (TOOL_NAMES).
- 화면 타깃 연령 → Tool 입력 코드는 TARGET_AGE_MAPPING을 쓴다.
- get_station_exit_traffic·get_district_congestion은 period에 시각을 넣지 않고 하루 전체로 조회한다.
- search_competitors는 COMPETITION_RADIUS_M(500)으로 조회한다.
- 후보 순서는 rank_market_scores로 정한다 (전 항목 누락 후보 제외).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from models.schemas import (
    SCORE_MAX_POINTS,
    AcademyDemandData,
    AnalysisPeriod,
    ErrorCode,
    MarketScore,
    MetricObservation,
    ScoringInput,
    StationTrafficData,
    ToolResult,
)

__all__ = [
    "POLICY_VERSION",
    "REFERENCE_PATH",
    "TOOL_NAMES",
    "TARGET_AGE_MAPPING",
    "COMPETITION_RADIUS_M",
    "ScoringReference",
    "load_reference",
    "compute_market_score",
    "calculate_market_score",
    "rank_market_scores",
]

POLICY_VERSION = "scoring-v1-draft"
_SOURCE = f"StudySpot 입지점수 계산 ({POLICY_VERSION})"
REFERENCE_PATH = Path(__file__).resolve().parents[1] / "data" / "mock" / "scoring_reference.json"

# ---------------------------------------------------------------------------
# Tool 연결 규칙
# ---------------------------------------------------------------------------

ACADEMY_TOOL = "get_academy_demand"
VISITOR_TOOL = "get_visitor_demographics"
STATION_TOOL = "get_station_exit_traffic"
CONGESTION_TOOL = "get_district_congestion"
RENT_TOOL = "get_rent_and_closure_data"
COMPETITOR_TOOL = "search_competitors"

TOOL_NAMES = MappingProxyType(
    {
        "academy_demand_score": ACADEMY_TOOL,
        "target_customer_score": VISITOR_TOOL,
        "station_traffic_score": STATION_TOOL,
        "activity_score": CONGESTION_TOOL,
        "rent_score": RENT_TOOL,
        "competition_score": COMPETITOR_TOOL,
    }
)
"""세부 점수 → ScoringInput.tool_results에서 찾을 key (Tool 이름)."""

TARGET_AGE_MAPPING = MappingProxyType(
    {
        "중학생": MappingProxyType({"school_age": "middle", "age_group": "10"}),
        "고등학생": MappingProxyType({"school_age": "high", "age_group": "10"}),
        "대학생": MappingProxyType({"school_age": "univ", "age_group": "20"}),
        "20대": MappingProxyType({"school_age": "univ", "age_group": "20"}),
        "30대 이상": MappingProxyType({"school_age": "all", "age_group": "30"}),
        "전체": MappingProxyType({"school_age": "all", "age_group": None}),
    }
)
"""화면 타깃 연령 → Tool 입력 코드.

- school_age: get_academy_demand의 target_age
- age_group: get_visitor_demographics의 target_age. "전체"는 None (조회하지 않고 모든 후보 10점)
"""

_ACADEMY_METRIC = ("estimated_academy_call_customers", "persons")
_VISITOR_METRIC = ("visitor_age_group_rate", "percent")
_STATION_METRIC = ("station_exit_user_count", "persons/hour")
_CONGESTION_METRIC = ("district_congestion_density", "persons/m2")
_MONTHLY_RENT_METRIC = ("monthly_rent_krw", "KRW/month")
_DEPOSIT_METRIC = ("deposit_krw", "KRW")

# ---------------------------------------------------------------------------
# 정책값 (docs/scoring.md 1-3절 가정값)
# ---------------------------------------------------------------------------

RATIO_ZERO = 0.5
"""기준값 대비 이 배율 이하 → 0점."""
RATIO_FULL = 1.5
"""기준값 대비 이 배율 이상 → 만점."""
RENT_FULL = 0.8
"""예산 대비 이 비율 이하 → 만점."""
RENT_ZERO = 1.2
"""예산 대비 이 비율 이상 → 0점."""
COMPETITION_RADIUS_M = 500
COMPETITION_ZERO_COUNT = 10
"""반경 안 경쟁점포가 이 개수 이상 → 0점."""
QUALITY_REAL = 1.0
QUALITY_MOCK = 0.5


# ---------------------------------------------------------------------------
# 기준값 스냅샷
# ---------------------------------------------------------------------------

_NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
_HourlyProfile = Annotated[list[_NonNegative], Field(min_length=24, max_length=24)]


class _ReferenceArea(BaseModel):
    """스냅샷의 지원 상권 하나. 값이 없는 항목은 비워 두고 중앙값 계산에서 뺀다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commercial_area_id: str
    area_name: str
    academy_call_customers_top5_sum: dict[str, _NonNegative] = Field(default_factory=dict)
    """school_age → 상위 5개 학원 추정 통화 고객 수 합"""
    visitor_age_group_rate_percent: dict[str, _NonNegative] = Field(default_factory=dict)
    """age_group → 방문자 중 해당 연령대 비율 (남녀 합, %)"""
    station_hourly_avg_users: _NonNegative | None = None
    """가까운 역의 하루 시간당 평균 출구 이용자 수"""
    congestion_density_by_hour: _HourlyProfile | None = None
    """0시~23시 상권 혼잡도 밀도 (persons/m2)"""


class ScoringReference(BaseModel):
    """기준값 스냅샷 (data/mock/scoring_reference.json). 기준값 = 지원 상권 값의 중앙값."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str
    is_mock: bool
    created_on: date
    source: str
    description: str
    areas: list[_ReferenceArea] = Field(min_length=1)

    def academy(self, school_age: str) -> float | None:
        return _median(area.academy_call_customers_top5_sum.get(school_age) for area in self.areas)

    def visitor(self, age_group: str) -> float | None:
        return _median(area.visitor_age_group_rate_percent.get(age_group) for area in self.areas)

    def station(self) -> float | None:
        return _median(area.station_hourly_avg_users for area in self.areas)

    def operating_share(self, hours: frozenset[int]) -> float | None:
        """운영시간대 혼잡도 비중의 중앙값."""
        shares = []
        for area in self.areas:
            profile = area.congestion_density_by_hour
            if profile is None or sum(profile) <= 0:
                continue
            shares.append(sum(profile[hour] for hour in sorted(hours)) / sum(profile))
        return _median(shares)


def _median(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.median(present) if present else None


def load_reference(path: Path | None = None) -> ScoringReference:
    """기준값 스냅샷을 읽는다. 파일이 없거나 형식이 틀리면 OSError·ValueError."""
    target = REFERENCE_PATH if path is None else path
    return ScoringReference.model_validate_json(target.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 항목별 계산
# ---------------------------------------------------------------------------


class _Missing(Exception):
    """세부 점수를 계산할 수 없음. 메시지가 missing_data 사유가 된다."""


class _AreaMismatch(Exception):
    """다른 상권의 조회 결과가 섞임 (계산 전체 거절)."""


@dataclass(frozen=True)
class _Item:
    normalized: float | None
    """0~1. None이면 계산 불가."""
    quality: float
    """신뢰도 계산용 데이터 품질 (1.0 실데이터 / 0.5 Mock / 0 누락)."""
    uses_reference: bool = False
    notes: tuple[str, ...] = ()
    """missing_data에 남길 사유 (점수가 있어도 일부 누락이면 기록)."""


def _clip(value: float) -> float:
    return min(1.0, max(0.0, value))


def _quality(result_is_mock: bool, observations: Iterable[MetricObservation]) -> float:
    if result_is_mock or any(observation.is_mock for observation in observations):
        return QUALITY_MOCK
    return QUALITY_REAL


def _successful_data(scoring_input: ScoringInput, tool_name: str) -> tuple[Any, bool]:
    result = scoring_input.tool_results.get(tool_name)
    if result is None:
        raise _Missing(f"{tool_name} 결과 없음")
    if not result.success:
        raise _Missing(f"{tool_name} 조회 실패 ({result.error_code})")
    return result.data, result.is_mock


def _validate(model: type[BaseModel], data: Any) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise _Missing("데이터 형식 오류") from exc


def _market_observations(data: Any) -> list[MetricObservation]:
    """market_tools 결과(data['observations'])를 공통 관측값 모델로 읽는다."""
    if not isinstance(data, dict) or not isinstance(data.get("observations"), list):
        raise _Missing("데이터 형식 오류")
    return [_validate(MetricObservation, item) for item in data["observations"]]


def _metric_values(
    observations: list[MetricObservation], metric: tuple[str, str], empty_reason: str
) -> list[MetricObservation]:
    """지정 지표의 관측값만 고른다. 단위가 다르거나 음수면 계산하지 않는다."""
    metric_name, unit = metric
    selected = [item for item in observations if item.metric_name == metric_name]
    if any(item.unit != unit for item in selected):
        raise _Missing(f"단위 불일치 ({unit} 필요)")
    present = [item for item in selected if item.value is not None]
    if not present:
        raise _Missing(empty_reason)
    if any(item.value < 0 for item in present):
        raise _Missing("데이터 오류 (음수 값)")
    return present


def _ratio_item(value: float, reference: float | None, quality: float) -> _Item:
    """기준값 대비 배율 정규화 (docs/scoring.md 2-1)."""
    if reference is None or reference <= 0:
        raise _Missing("기준값 없음")
    ratio = value / reference
    return _Item(_clip((ratio - RATIO_ZERO) / (RATIO_FULL - RATIO_ZERO)), quality, uses_reference=True)


def _require_full_day(scoring_input: ScoringInput) -> None:
    if scoring_input.period.start_time is not None:
        raise _Missing("하루 전체 데이터 필요 (분석 기간에 시각이 지정됨)")


def _slot_hour(observation: MetricObservation) -> int:
    time_slot = observation.dimensions.get("time_slot")
    start = time_slot.split("-")[0] if time_slot else observation.period.start_time
    if start is None:
        raise _Missing("시간대 정보 없음")
    return int(start[:2])


def _hourly_totals(observations: list[MetricObservation], period: AnalysisPeriod) -> dict[tuple[date, int], float]:
    """(날짜, 시) → 합계. 출구가 여러 개면 같은 시간대끼리 더한다."""
    totals: dict[tuple[date, int], float] = {}
    for observation in observations:
        if not period.start_date <= observation.period.start_date <= period.end_date:
            raise _Missing("기간 불일치")
        key = (observation.period.start_date, _slot_hour(observation))
        totals[key] = totals.get(key, 0.0) + observation.value
    return totals


def _in_operating_time(current: str, start: str, end: str) -> bool:
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _operating_hours(start: str, end: str) -> frozenset[int]:
    """운영시간에 시작 시각이 들어가는 시간대(0~23시). 시작=종료는 24시간 운영."""
    if start == end:
        return frozenset(range(24))
    return frozenset(hour for hour in range(24) if _in_operating_time(f"{hour:02d}:00", start, end))


def _academy(scoring_input: ScoringInput, reference: ScoringReference, mapping: Mapping[str, Any] | None) -> _Item:
    if mapping is None:
        raise _Missing("지원하지 않는 타깃 연령")
    data, is_mock = _successful_data(scoring_input, ACADEMY_TOOL)
    payload = _validate(AcademyDemandData, data)
    observations = _metric_values(payload.observations, _ACADEMY_METRIC, "학원 순위 데이터 없음")
    value = sum(item.value for item in observations)
    return _ratio_item(value, reference.academy(mapping["school_age"]), _quality(is_mock, observations))


def _target(scoring_input: ScoringInput, reference: ScoringReference, mapping: Mapping[str, Any] | None) -> _Item:
    if mapping is None:
        raise _Missing("지원하지 않는 타깃 연령")
    age_group = mapping["age_group"]
    if age_group is None:
        return _Item(0.5, QUALITY_REAL)
    data, is_mock = _successful_data(scoring_input, VISITOR_TOOL)
    if not isinstance(data, dict) or data.get("target_age_group") != age_group:
        raise _Missing("연령대 불일치")
    observations = _metric_values(_market_observations(data), _VISITOR_METRIC, "방문자 연령 데이터 없음")
    value = sum(item.value for item in observations)
    if value > 100:
        raise _Missing("데이터 오류 (비율 100% 초과)")
    return _ratio_item(value, reference.visitor(age_group), _quality(is_mock, observations))


def _station(scoring_input: ScoringInput, reference: ScoringReference) -> _Item:
    _require_full_day(scoring_input)
    data, is_mock = _successful_data(scoring_input, STATION_TOOL)
    payload = _validate(StationTrafficData, data)
    observations = _metric_values(payload.observations, _STATION_METRIC, "출구 통행량 데이터 없음")
    totals = _hourly_totals(observations, scoring_input.period)
    value = sum(totals.values()) / len(totals)
    return _ratio_item(value, reference.station(), _quality(is_mock, observations))


def _activity(scoring_input: ScoringInput, reference: ScoringReference, hours: frozenset[int]) -> _Item:
    _require_full_day(scoring_input)
    data, is_mock = _successful_data(scoring_input, CONGESTION_TOOL)
    observations = _metric_values(_market_observations(data), _CONGESTION_METRIC, "상권 혼잡도 데이터 없음")
    totals = _hourly_totals(observations, scoring_input.period)
    whole_day = sum(totals.values())
    if whole_day <= 0:
        raise _Missing("하루 전체 혼잡도가 0")
    share = sum(value for (_, hour), value in sorted(totals.items()) if hour in hours) / whole_day
    return _ratio_item(share, reference.operating_share(hours), _quality(is_mock, observations))


def _budget_fit(cost: float, budget: int) -> float:
    """예산 대비 비율 정규화 (docs/scoring.md 3-5). 예산 0이면 비용 0일 때만 만점."""
    if budget == 0:
        return 1.0 if cost == 0 else 0.0
    ratio = cost / budget
    return _clip((RENT_ZERO - ratio) / (RENT_ZERO - RENT_FULL))


def _rent(scoring_input: ScoringInput) -> _Item:
    data, is_mock = _successful_data(scoring_input, RENT_TOOL)
    observations = _market_observations(data)
    conditions = scoring_input.conditions
    parts = (
        ("월세", _MONTHLY_RENT_METRIC, conditions.monthly_rent_budget),
        ("보증금", _DEPOSIT_METRIC, conditions.deposit_budget),
    )
    fits: dict[str, float] = {}
    used: list[MetricObservation] = []
    reasons: list[str] = []
    for label, metric, budget in parts:
        try:
            selected = _metric_values(observations, metric, f"{label} 데이터 없음")
        except _Missing as exc:
            reasons.append(str(exc))
            continue
        if len(selected) != 1:
            reasons.append(f"{label} 값이 여러 개")
            continue
        fits[label] = _budget_fit(selected[0].value, budget)
        used.extend(selected)
    if not fits:
        raise _Missing(" · ".join(reasons))
    notes = tuple(f"{reason} ({'·'.join(fits)}만 반영)" for reason in reasons)
    return _Item(min(fits.values()), _quality(is_mock, used), notes=notes)


def _competition(scoring_input: ScoringInput) -> _Item:
    data, is_mock = _successful_data(scoring_input, COMPETITOR_TOOL)
    if not isinstance(data, dict) or not isinstance(data.get("competitors"), list):
        raise _Missing("데이터 형식 오류")
    if data.get("radius_m") != COMPETITION_RADIUS_M:
        raise _Missing(f"반경 불일치 ({COMPETITION_RADIUS_M}m 기준)")
    count = len(data["competitors"])
    return _Item(_clip(1 - count / COMPETITION_ZERO_COUNT), QUALITY_MOCK if is_mock else QUALITY_REAL)


def _run(calculate: Callable[[], _Item]) -> _Item:
    try:
        return calculate()
    except _Missing as exc:
        return _Item(None, 0.0, notes=(str(exc),))


def _score_items(scoring_input: ScoringInput, reference: ScoringReference) -> dict[str, _Item]:
    conditions = scoring_input.conditions
    mapping = TARGET_AGE_MAPPING.get(conditions.target_age)
    hours = _operating_hours(conditions.operating_start_time, conditions.operating_end_time)
    calculators: dict[str, Callable[[], _Item]] = {
        "academy_demand_score": lambda: _academy(scoring_input, reference, mapping),
        "target_customer_score": lambda: _target(scoring_input, reference, mapping),
        "station_traffic_score": lambda: _station(scoring_input, reference),
        "activity_score": lambda: _activity(scoring_input, reference, hours),
        "rent_score": lambda: _rent(scoring_input),
        "competition_score": lambda: _competition(scoring_input),
    }
    return {name: _run(calculators[name]) for name in SCORE_MAX_POINTS}


# ---------------------------------------------------------------------------
# 합산·반올림
# ---------------------------------------------------------------------------


def _round_half_up(value: float, digits: int) -> Decimal:
    """사사오입. 부동소수 오차(7.4999999…)를 먼저 소수 9자리에서 정리한다 (docs/scoring.md 2-6)."""
    cleaned = Decimal(str(value)).quantize(Decimal("1e-9"))
    return cleaned.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def _build_market_score(items: dict[str, _Item]) -> MarketScore:
    points: dict[str, Decimal | None] = {}
    missing_data: list[str] = []
    for name, max_points in SCORE_MAX_POINTS.items():
        item = items[name]
        missing_data.extend(f"{name}: {note}" for note in item.notes)
        points[name] = None if item.normalized is None else _round_half_up(item.normalized * max_points, 1)
    total = sum((value for value in points.values() if value is not None), Decimal("0"))
    confidence = sum(max_points * items[name].quality for name, max_points in SCORE_MAX_POINTS.items()) / 100
    return MarketScore(
        **{name: None if value is None else float(value) for name, value in points.items()},
        total_score=float(total),
        confidence=float(_round_half_up(confidence, 2)),
        missing_data=missing_data,
    )


def _check_same_area(scoring_input: ScoringInput) -> None:
    expected = scoring_input.area.commercial_area_id
    for tool_name, result in scoring_input.tool_results.items():
        if not result.success or not isinstance(result.data, dict):
            continue
        found = result.data.get("commercial_area_id")
        area = result.data.get("area")
        if found is None and isinstance(area, dict):
            found = area.get("commercial_area_id")
        if found is not None and found != expected:
            raise _AreaMismatch(tool_name)


def _failure(code: ErrorCode, message: str) -> ToolResult:
    return ToolResult(success=False, source=_SOURCE, data={}, error_code=code, error_message=message, is_mock=False)


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------


def compute_market_score(scoring_input: ScoringInput | Mapping[str, Any], reference: ScoringReference) -> ToolResult:
    """기준값 스냅샷을 직접 지정해 계산한다 (테스트·민감도 분석용). Agent는 calculate_market_score를 쓴다."""
    try:
        scoring_input = ScoringInput.model_validate(scoring_input)
    except ValidationError:
        return _failure(ErrorCode.INVALID_INPUT, "점수 계산 입력 형식이 올바르지 않습니다.")
    try:
        _check_same_area(scoring_input)
        items = _score_items(scoring_input, reference)
        score = _build_market_score(items)
    except _AreaMismatch as exc:
        return _failure(ErrorCode.INVALID_INPUT, f"다른 상권의 조회 결과가 섞여 있습니다 ({exc}).")
    except Exception:
        return _failure(ErrorCode.TOOL_INTERNAL_ERROR, "입지점수 계산 중 오류가 발생했습니다.")

    uses_mock_reference = reference.is_mock and any(item.uses_reference for item in items.values())
    is_mock = uses_mock_reference or any(item.quality == QUALITY_MOCK for item in items.values())
    return ToolResult(
        success=True,
        source=_SOURCE,
        data=score.model_dump(mode="json"),
        error_code=None,
        error_message=None,
        is_mock=is_mock,
    )


def calculate_market_score(scoring_input: ScoringInput | Mapping[str, Any]) -> ToolResult:
    """상권 하나의 입지점수를 계산한다. 정상 data는 MarketScore 직렬화 사전."""
    try:
        reference = load_reference()
    except (OSError, ValueError):
        return _failure(ErrorCode.TOOL_INTERNAL_ERROR, "기준값 스냅샷을 읽을 수 없습니다.")
    return compute_market_score(scoring_input, reference)


def rank_market_scores(scores: Mapping[str, MarketScore | Mapping[str, Any]]) -> list[str]:
    """상권 ID → MarketScore를 추천 순서의 상권 ID 목록으로 바꾼다.

    총점 높은 순 → 신뢰도 높은 순 → commercial_area_id 오름차순. 전 항목 누락 후보는 뺀다.
    """
    candidates = []
    for area_id, score in scores.items():
        score = MarketScore.model_validate(score)
        if any(value is not None for value in score.score_values().values()):
            candidates.append((area_id, score))
    candidates.sort(key=lambda pair: (-pair[1].total_score, -pair[1].confidence, pair[0]))
    return [area_id for area_id, _ in candidates]
