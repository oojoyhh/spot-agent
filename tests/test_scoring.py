"""입지점수 계산 테스트 (SCR-01~09).

기대값은 docs/scoring.md 4절처럼 사람이 계산한 값이다. 구현 함수로 다시 계산하지 않는다.
실행: python -m pytest tests/test_scoring.py
"""

import copy
import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.schemas import MarketScore
from tools import scoring_tools
from tools.scoring_tools import (
    TARGET_AGE_MAPPING,
    calculate_market_score,
    compute_market_score,
    load_reference,
    rank_market_scores,
)

MOCK_DIR = Path(__file__).resolve().parents[1] / "data" / "mock"
REFERENCE = load_reference()
EXPECTED = json.loads((MOCK_DIR / "scoring_expected.json").read_text(encoding="utf-8"))
_EXAMPLE = json.loads((MOCK_DIR / "scoring_example_input.json").read_text(encoding="utf-8"))

ACADEMY = "get_academy_demand"
VISITOR = "get_visitor_demographics"
STATION = "get_station_exit_traffic"
CONGESTION = "get_district_congestion"
RENT = "get_rent_and_closure_data"
COMPETITOR = "search_competitors"


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


def example_input(name: str = "example_a") -> dict:
    """예제 A 입력. B는 경쟁점포 조회 실패, C는 조회 결과 없음."""
    raw = copy.deepcopy(_EXAMPLE)
    if name == "example_b":
        raw["tool_results"][COMPETITOR] = failed_result()
    elif name == "example_c":
        raw["tool_results"] = {}
    return raw


def failed_result(code: str = "API_TIMEOUT") -> dict:
    return {"success": False, "source": "test", "data": {}, "error_code": code, "error_message": "조회 실패", "is_mock": False}


def score(raw: dict, reference=REFERENCE) -> dict:
    result = compute_market_score(raw, reference)
    assert result.success, result.error_message
    return result.data


def expected(name: str) -> dict:
    return {key: value for key, value in EXPECTED[name].items() if key != "is_mock"}


def observations(raw: dict, tool_name: str) -> list[dict]:
    return raw["tool_results"][tool_name]["data"]["observations"]


def set_academy_total(raw: dict, total: float) -> None:
    items = observations(raw, ACADEMY)
    items[0]["value"] = float(total)
    for item in items[1:]:
        item["value"] = 0.0


def set_rent(raw: dict, *, monthly: float | None = None, deposit: float | None = None) -> None:
    for item in observations(raw, RENT):
        if item["metric_name"] == "monthly_rent_krw" and monthly is not None:
            item["value"] = float(monthly)
        if item["metric_name"] == "deposit_krw" and deposit is not None:
            item["value"] = float(deposit)


def make_real(raw: dict) -> dict:
    """임대료 Mock 표시를 지워 모든 조회 결과를 실데이터로 만든다."""
    rent = raw["tool_results"][RENT]
    rent["is_mock"] = False
    for item in rent["data"]["observations"]:
        item["is_mock"] = False
    return raw


def market_score(total: float, confidence: float) -> MarketScore:
    """순위 테스트용. total을 학원·타깃·지하철·경쟁 순으로 채운다."""
    values, left = {}, total
    for name, max_points in (("academy_demand_score", 25), ("target_customer_score", 20),
                             ("station_traffic_score", 15), ("activity_score", 15),
                             ("rent_score", 15), ("competition_score", 10)):
        values[name] = min(left, max_points)
        left -= values[name]
    return MarketScore(**values, total_score=total, confidence=confidence)


# ---------------------------------------------------------------------------
# SCR-01 손 계산 예제
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["example_a", "example_b", "example_c"])
def test_scr01_examples_match_hand_calculation(name):
    result = compute_market_score(example_input(name), REFERENCE)

    assert result.success
    assert result.error_code is None
    assert result.data == expected(name)
    assert result.is_mock is EXPECTED[name]["is_mock"]


def test_scr01_reference_medians_match_doc():
    """docs/scoring.md 5절 표의 중앙값."""
    assert REFERENCE.academy("high") == 1000
    assert REFERENCE.academy("all") == 2500
    assert REFERENCE.visitor("10") == 20
    assert REFERENCE.station() == 500
    assert REFERENCE.operating_share(frozenset(range(9, 23))) == pytest.approx(0.8)


def test_scr01_calculate_market_score_uses_snapshot():
    result = calculate_market_score(example_input())

    assert result.success
    assert result.data == expected("example_a")


def test_scr01_missing_snapshot_is_internal_error(monkeypatch, tmp_path):
    monkeypatch.setattr(scoring_tools, "REFERENCE_PATH", tmp_path / "none.json")

    result = calculate_market_score(example_input())

    assert not result.success
    assert result.error_code == "TOOL_INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# SCR-02 재현성
# ---------------------------------------------------------------------------


def test_scr02_same_input_same_result():
    first = score(example_input())
    assert all(score(example_input()) == first for _ in range(3))


def test_scr02_order_does_not_matter():
    raw = example_input()
    raw["tool_results"] = dict(reversed(list(raw["tool_results"].items())))
    for tool_name in (ACADEMY, STATION, CONGESTION, RENT):
        random.Random(0).shuffle(observations(raw, tool_name))

    assert score(raw) == expected("example_a")


# ---------------------------------------------------------------------------
# SCR-03 경계값·이상치
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "points"),
    [
        (400, 0.0),    # 0.4배 → 0점
        (500, 0.0),    # 0.5배 → 0점
        (990, 12.3),   # 0.49 × 25 = 12.25 → 사사오입 12.3 (round()는 12.2)
        (1000, 12.5),  # 1.0배 → 절반
        (1500, 25.0),  # 1.5배 → 만점
        (3000, 25.0),  # 이상치 → 만점에서 잘림
    ],
)
def test_scr03_academy_ratio_boundaries(total, points):
    raw = example_input()
    set_academy_total(raw, total)

    assert score(raw)["academy_demand_score"] == points


@pytest.mark.parametrize(("count", "points"), [(0, 10.0), (3, 7.0), (10, 0.0), (15, 0.0)])
def test_scr03_competition_boundaries(count, points):
    raw = example_input()
    item = raw["tool_results"][COMPETITOR]["data"]["competitors"][0]
    raw["tool_results"][COMPETITOR]["data"]["competitors"] = [
        {**item, "poi_id": f"P{index}"} for index in range(count)
    ]

    assert score(raw)["competition_score"] == points


@pytest.mark.parametrize(
    ("monthly", "deposit", "points"),
    [
        (2_400_000, 20_000_000, 15.0),  # 월세 80% → 만점
        (3_300_000, 20_000_000, 3.8),   # 월세 110% → 0.25 × 15 = 3.75 → 3.8
        (3_600_000, 20_000_000, 0.0),   # 월세 120% → 0점
        (2_400_000, 36_000_000, 0.0),   # 보증금 120% → 더 부담되는 쪽 기준 0점
        (2_400_000, 30_000_000, 7.5),   # 보증금 100% → 7.5
    ],
)
def test_scr03_rent_boundaries(monthly, deposit, points):
    raw = example_input()
    set_rent(raw, monthly=monthly, deposit=deposit)

    assert score(raw)["rent_score"] == points


def test_scr03_zero_budget():
    raw = example_input()
    raw["conditions"]["monthly_rent_budget"] = 0

    assert score(raw)["rent_score"] == 0.0


def test_scr03_negative_value_is_data_error():
    raw = example_input()
    observations(raw, ACADEMY)[0]["value"] = -1.0

    data = score(raw)

    assert data["academy_demand_score"] is None
    assert "academy_demand_score: 데이터 오류 (음수 값)" in data["missing_data"]


def test_scr03_rate_over_100_is_data_error():
    raw = example_input()
    observations(raw, VISITOR)[0]["value"] = 95.0

    data = score(raw)

    assert data["target_customer_score"] is None
    assert "target_customer_score: 데이터 오류 (비율 100% 초과)" in data["missing_data"]


# ---------------------------------------------------------------------------
# SCR-04 실제 0·일부 누락·전체 누락
# ---------------------------------------------------------------------------


def test_scr04_zero_competitors_is_real_zero():
    raw = example_input()
    raw["tool_results"][COMPETITOR]["data"]["competitors"] = []

    data = score(raw)

    assert data["competition_score"] == 10.0
    assert not any(item.startswith("competition_score") for item in data["missing_data"])


def test_scr04_empty_academy_ranking_is_missing_not_zero():
    raw = example_input()
    academy = raw["tool_results"][ACADEMY]["data"]
    academy["observations"] = []
    academy["missing_data"] = ["학원 순위 데이터가 없습니다. 학원이 0개라는 의미는 아닙니다."]

    data = score(raw)

    assert data["academy_demand_score"] is None
    assert data["total_score"] == 46.5  # 64.0 - 17.5
    assert "academy_demand_score: 학원 순위 데이터 없음" in data["missing_data"]


def test_scr04_partial_rent_uses_available_part():
    raw = example_input()
    rent = raw["tool_results"][RENT]["data"]
    rent["observations"] = [item for item in rent["observations"] if item["metric_name"] != "deposit_krw"]

    data = score(raw)

    assert data["rent_score"] == 7.5
    assert "rent_score: 보증금 데이터 없음 (월세만 반영)" in data["missing_data"]


def test_scr04_all_missing_candidate_is_excluded_from_ranking():
    scores = {"AREA-A": score(example_input()), "AREA-C": score(example_input("example_c"))}

    assert rank_market_scores(scores) == ["AREA-A"]


def test_scr04_ranking_tie_break():
    scores = {
        "B": market_score(60.0, 0.9),
        "A": market_score(60.0, 0.9),
        "C": market_score(60.0, 0.95),
        "D": market_score(70.0, 0.5),
    }

    assert rank_market_scores(scores) == ["D", "C", "A", "B"]


# ---------------------------------------------------------------------------
# SCR-05 실데이터·Mock 혼합
# ---------------------------------------------------------------------------


def test_scr05_real_data_and_real_reference_is_not_mock():
    result = compute_market_score(make_real(example_input()), REFERENCE.model_copy(update={"is_mock": False}))

    assert result.is_mock is False
    assert result.data["confidence"] == 1.0


def test_scr05_mock_reference_marks_result_as_mock():
    result = compute_market_score(make_real(example_input()), REFERENCE)

    assert result.is_mock is True
    assert result.data["confidence"] == 1.0  # 신뢰도는 데이터 품질만 반영


def test_scr05_fallback_mock_lowers_confidence():
    raw = example_input()
    academy = raw["tool_results"][ACADEMY]
    academy.update(is_mock=True, error_code="API_TIMEOUT", error_message="Mock 대체")

    result = compute_market_score(raw, REFERENCE)

    assert result.is_mock is True
    assert result.data["academy_demand_score"] == 17.5
    assert result.data["confidence"] == 0.8  # (12.5 + 20 + 15 + 15 + 7.5 + 10) ÷ 100


def test_scr05_mock_observation_inside_real_result():
    raw = make_real(example_input())
    observations(raw, ACADEMY)[0]["is_mock"] = True

    result = compute_market_score(raw, REFERENCE.model_copy(update={"is_mock": False}))

    assert result.is_mock is True
    assert result.data["confidence"] == 0.88  # (12.5 + 75) ÷ 100 = 0.875 → 0.88


# ---------------------------------------------------------------------------
# SCR-06 단위·기간·상권 불일치
# ---------------------------------------------------------------------------


def test_scr06_other_area_result_is_rejected():
    raw = example_input()
    raw["tool_results"][ACADEMY]["data"]["commercial_area_id"] = "OTHER"

    result = compute_market_score(raw, REFERENCE)

    assert not result.success
    assert result.error_code == "INVALID_INPUT"
    assert result.data == {}


def test_scr06_unit_mismatch():
    raw = example_input()
    for item in observations(raw, STATION):
        item["unit"] = "persons"

    data = score(raw)

    assert data["station_traffic_score"] is None
    assert "station_traffic_score: 단위 불일치 (persons/hour 필요)" in data["missing_data"]


def test_scr06_period_mismatch():
    raw = example_input()
    for item in observations(raw, CONGESTION):
        item["period"]["start_date"] = item["period"]["end_date"] = "2026-09-09"

    data = score(raw)

    assert data["activity_score"] is None
    assert "activity_score: 기간 불일치" in data["missing_data"]


def test_scr06_period_with_time_needs_full_day():
    raw = example_input()
    raw["period"].update(start_time="09:00", end_time="23:00")

    data = score(raw)

    assert data["station_traffic_score"] is None
    assert data["activity_score"] is None
    assert "activity_score: 하루 전체 데이터 필요 (분석 기간에 시각이 지정됨)" in data["missing_data"]


def test_scr06_age_group_mismatch():
    raw = example_input()
    raw["tool_results"][VISITOR]["data"]["target_age_group"] = "20"

    data = score(raw)

    assert data["target_customer_score"] is None
    assert "target_customer_score: 연령대 불일치" in data["missing_data"]


def test_scr06_radius_mismatch():
    raw = example_input()
    raw["tool_results"][COMPETITOR]["data"]["radius_m"] = 1000

    data = score(raw)

    assert data["competition_score"] is None
    assert "competition_score: 반경 불일치 (500m 기준)" in data["missing_data"]


def test_scr06_unknown_target_age():
    raw = example_input()
    raw["conditions"]["target_age"] = "40대"

    data = score(raw)

    assert data["academy_demand_score"] is None
    assert data["target_customer_score"] is None
    assert "target_customer_score: 지원하지 않는 타깃 연령" in data["missing_data"]


def test_scr06_incomplete_input_is_rejected():
    raw = example_input()
    raw["conditions"]["target_age"] = None

    result = compute_market_score(raw, REFERENCE)

    assert not result.success
    assert result.error_code == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# SCR-07 총점 변조·잘못된 값
# ---------------------------------------------------------------------------


def test_scr07_tampered_total_is_rejected():
    data = score(example_input())
    data["total_score"] = 70.0

    with pytest.raises(ValidationError):
        MarketScore.model_validate(data)


def test_scr07_score_over_max_is_rejected():
    data = score(example_input())
    data["competition_score"] = 12.0
    data["total_score"] += 5.0

    with pytest.raises(ValidationError):
        MarketScore.model_validate(data)


def test_scr07_none_without_reason_is_rejected():
    data = score(example_input("example_b"))
    data["missing_data"] = []

    with pytest.raises(ValidationError):
        MarketScore.model_validate(data)


# ---------------------------------------------------------------------------
# SCR-08 직렬화 후 복원
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["example_a", "example_b", "example_c"])
def test_scr08_roundtrip_keeps_values_and_none(name):
    data = score(example_input(name))

    restored = MarketScore.model_validate(json.loads(json.dumps(data)))

    assert restored.model_dump(mode="json") == data


# ---------------------------------------------------------------------------
# SCR-09 우선순위 변경
# ---------------------------------------------------------------------------


def test_scr09_priority_metrics_do_not_change_score():
    raw = example_input()
    raw["conditions"]["priority_metrics"] = ["rent_score", "competition_score"]

    assert score(raw) == expected("example_a")


# ---------------------------------------------------------------------------
# 타깃 연령·운영시간
# ---------------------------------------------------------------------------


def test_target_age_options_match_ui():
    """명하님 화면 선택지 (ui/contracts.py TARGET_AGE_OPTIONS)."""
    assert set(TARGET_AGE_MAPPING) == {"중학생", "고등학생", "대학생", "20대", "30대 이상", "전체"}


def test_target_all_gives_everyone_half_points():
    raw = example_input()
    raw["conditions"]["target_age"] = "전체"

    data = score(raw)

    assert data["target_customer_score"] == 10.0
    assert data["academy_demand_score"] == 0.0  # 1,200 ÷ 전체 학령 기준 2,500 = 0.48배
    assert data["total_score"] == 36.5


def test_24_hour_operation_gives_everyone_half_points():
    raw = example_input()
    raw["conditions"].update(operating_start_time="09:00", operating_end_time="09:00")

    assert score(raw)["activity_score"] == 7.5


def test_operating_hours_across_midnight():
    """18:00~02:00: 18~23시와 0~1시 (8시간). 이 시간대 밀도를 4배로 → 비중 3.2 ÷ 4.8 = 67%.

    기준값 = 기준 상권 3의 비중 (5 × 0.2 + 3 × 0.07) ÷ 3.5 = 34.6% → 1.93배 → 만점.
    자정 이후 2시간이 빠지면 2.4 ÷ 4.8 = 50% → 1.45배 → 14.2점이 된다.
    """
    raw = example_input()
    raw["conditions"].update(operating_start_time="18:00", operating_end_time="02:00")
    for item in observations(raw, CONGESTION):
        if item["metric_name"] == "district_congestion_density":
            hour = int(item["dimensions"]["time_slot"][:2])
            item["value"] = 0.4 if hour >= 18 or hour < 2 else 0.1

    assert score(raw)["activity_score"] == 15.0
