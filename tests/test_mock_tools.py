from datetime import date

import pytest

from models.schemas import AcademyDemandData, AnalysisPeriod, AreaIdentity, StationTrafficData, ToolResult
from tools.mock_tools import build_mock_result


def _area() -> AreaIdentity:
    return AreaIdentity(
        commercial_area_id="9307",
        administrative_code="1168010100",
        area_name="역삼역남부 3번출구",
        latitude=37.50012959,
        longitude=127.03529551,
    )


def _period() -> AnalysisPeriod:
    return AnalysisPeriod(
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 10),
        day_types=["weekday"],
        start_time="18:00",
        end_time="20:00",
    )


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("search_supported_districts", {"preferred_region": "강남구"}),
        ("resolve_area_entities", {"selected_candidate_id": "9307"}),
        ("get_academy_demand", {"area": _area(), "period": _period(), "school_age": "high"}),
        ("get_station_exit_traffic", {"station_id": "221", "period": _period()}),
        ("get_district_congestion", {"area": _area(), "period": _period()}),
        ("get_visitor_demographics", {"area": _area(), "target_age": "20대", "period": _period()}),
        ("search_competitors", {"area": _area(), "radius_m": 500}),
    ],
)
def test_supported_mock_results_follow_tool_result_contract(tool_name: str, args: dict) -> None:
    result = build_mock_result(tool_name, args)

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.is_mock is True
    assert result.source == f"mock:{tool_name}"
    assert result.error_code is None


def test_academy_and_station_mock_payloads_use_common_models() -> None:
    academy = build_mock_result(
        "get_academy_demand",
        {"area": _area().model_dump(mode="json"), "period": _period().model_dump(mode="json"), "school_age": "high"},
    )
    traffic = build_mock_result(
        "get_station_exit_traffic",
        {"station_id": "221", "period": _period().model_dump(mode="json")},
    )

    academy_data = AcademyDemandData.model_validate(academy.data)
    traffic_data = StationTrafficData.model_validate(traffic.data)
    assert academy_data.observations[0].is_mock is True
    assert traffic_data.observations[0].is_mock is True
    assert traffic_data.observations[0].dimensions["time_slot"] == "18:00-19:00"
