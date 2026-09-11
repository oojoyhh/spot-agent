from typing import get_type_hints

from models.schemas import StationTrafficData, ToolResult
from tools.academy_tools import get_academy_demand
from tools.api_types import SchoolAge, VisitorTargetAge
from tools.market_tools import get_visitor_demographics
from tools.subway_tools import _parse_station_exit_traffic, find_nearby_stations


def test_public_api_tool_type_contracts() -> None:
    academy_hints = get_type_hints(get_academy_demand)
    visitor_hints = get_type_hints(get_visitor_demographics)
    nearby_hints = get_type_hints(find_nearby_stations)

    assert academy_hints["school_age"] == SchoolAge
    assert academy_hints["return"] is ToolResult
    assert visitor_hints["target_age"] == VisitorTargetAge
    assert visitor_hints["return"] is ToolResult
    assert nearby_hints["radius_m"] is int
    assert nearby_hints["return"] is ToolResult


def test_subway_parser_returns_common_model_type() -> None:
    assert get_type_hints(_parse_station_exit_traffic)["return"] is StationTrafficData
