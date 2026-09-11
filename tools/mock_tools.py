"""외부 API 장애 시 사용하는 JSON 기반 Mock provider.

Mock 값은 ``data/mock/api_fallback.json``에서만 관리한다. 이 모듈은 실제 API
Tool과 같은 ``ToolResult.data`` 구조를 만들며, Middleware가 원래 오류 코드와
설명을 덧붙인다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, cast

from langchain.messages import ToolMessage

from models.schemas import (
    AcademyDemandData,
    AnalysisPeriod,
    AreaIdentity,
    MetricObservation,
    StationTrafficData,
    ToolResult,
)
from tools.api_types import SchoolAge, VisitorTargetAge

__all__ = ["build_mock_result", "mock_tool_call_provider"]

_MOCK_PATH = Path(__file__).resolve().parents[1] / "data" / "mock" / "api_fallback.json"
_SCHOOL_AGE_LABELS: dict[SchoolAge, str] = {
    "preschool": "영유아",
    "elementary": "초등학생",
    "middle": "중학생",
    "high": "고등학생",
    "univ": "대학생",
    "all": "전체",
}
_VISITOR_AGE_GROUPS: dict[VisitorTargetAge, str] = {
    "10세 미만": "0",
    "10대": "10",
    "20대": "20",
    "30대": "30",
    "40대": "40",
    "50대": "50",
    "60대": "60",
    "70대": "70",
    "80대": "80",
    "90대": "90",
    "100세 이상": "100_over",
}


def _load_mock() -> dict[str, Any]:
    payload = json.loads(_MOCK_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Mock 최상위 값은 객체여야 합니다")
    return payload


def _source(tool_name: str) -> str:
    return f"mock:{tool_name}"


def _result(tool_name: str, data: dict[str, Any] | list[Any]) -> ToolResult:
    return ToolResult(
        success=True,
        source=_source(tool_name),
        data=data,
        error_code=None,
        error_message=None,
        is_mock=True,
    )


def _area(value: Any) -> AreaIdentity:
    return value if isinstance(value, AreaIdentity) else AreaIdentity.model_validate(value)


def _period(value: Any) -> AnalysisPeriod:
    return value if isinstance(value, AnalysisPeriod) else AnalysisPeriod.model_validate(value)


def _mock_moment(period: AnalysisPeriod) -> datetime:
    hour, minute = (18, 0)
    if period.start_time is not None:
        hour, minute = map(int, period.start_time.split(":"))
    return datetime.combine(period.start_date, datetime.min.time()).replace(hour=hour, minute=minute)


def _observation_period(period: AnalysisPeriod) -> tuple[AnalysisPeriod, str]:
    start = _mock_moment(period)
    end = start + timedelta(hours=1)
    day_type = period.day_types[0]
    return (
        AnalysisPeriod(
            start_date=start.date(),
            end_date=start.date(),
            timezone=period.timezone,
            day_types=[day_type],
            start_time=start.strftime("%H:%M"),
            end_time=end.strftime("%H:%M"),
        ),
        f"{start:%H:%M}-{end:%H:%M}",
    )


def _mock_areas(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("areas")
    if not isinstance(rows, list):
        raise ValueError("Mock areas가 배열이 아닙니다")
    return rows


def _search_supported_districts(args: Mapping[str, Any], payload: Mapping[str, Any]) -> ToolResult | None:
    keyword = "".join(str(args.get("preferred_region", "")).split()).casefold()
    if not keyword:
        return None
    matches = []
    for row in _mock_areas(payload):
        aliases = row.get("aliases", [])
        searchable = [row.get("area_name", ""), *aliases]
        if any(keyword in "".join(str(value).split()).casefold() for value in searchable):
            matches.append(AreaIdentity.model_validate({key: value for key, value in row.items() if key != "aliases"}))
    return _result("search_supported_districts", [area.model_dump(mode="json") for area in matches]) if matches else None


def _resolve_area_entities(args: Mapping[str, Any], payload: Mapping[str, Any]) -> ToolResult | None:
    candidate_id = str(args.get("selected_candidate_id", "")).strip()
    for row in _mock_areas(payload):
        if row.get("commercial_area_id") == candidate_id:
            area = AreaIdentity.model_validate({key: value for key, value in row.items() if key != "aliases"})
            return _result("resolve_area_entities", area.model_dump(mode="json"))
    return None


def _academy(args: Mapping[str, Any], payload: Mapping[str, Any]) -> ToolResult:
    area = _area(args["area"])
    period = _period(args["period"])
    school_age = cast(SchoolAge, args.get("school_age", "all"))
    values = payload["academy"]
    observation = MetricObservation(
        metric_name="estimated_academy_call_customers",
        value=float(values["estimated_academy_call_customers"]),
        unit="persons",
        period=period,
        source=_source("get_academy_demand"),
        is_mock=True,
        dimensions={
            "academy_id": str(values["academy_id"]),
            "academy_name": str(values["academy_name"]),
            "category": str(values["category"]),
            "school_age": _SCHOOL_AGE_LABELS[school_age],
        },
    )
    data = AcademyDemandData(
        commercial_area_id=area.commercial_area_id,
        administrative_code=area.administrative_code,
        observations=[observation],
        missing_data=[],
    )
    return _result("get_academy_demand", data.model_dump(mode="json"))


def _station_traffic(args: Mapping[str, Any], payload: Mapping[str, Any]) -> ToolResult:
    station_id = str(args["station_id"])
    period = _period(args["period"])
    item_period, time_slot = _observation_period(period)
    values = payload["station_exit_traffic"]
    observation = MetricObservation(
        metric_name="station_exit_user_count",
        value=float(values["persons_per_hour"]),
        unit="persons/hour",
        period=item_period,
        source=_source("get_station_exit_traffic"),
        is_mock=True,
        dimensions={
            "exit_number": str(values["exit_number"]),
            "day_type": item_period.day_types[0],
            "time_slot": time_slot,
        },
    )
    data = StationTrafficData(station_id=station_id, observations=[observation], missing_data=[])
    return _result("get_station_exit_traffic", data.model_dump(mode="json"))


def _congestion(args: Mapping[str, Any], payload: Mapping[str, Any]) -> ToolResult:
    area = _area(args["area"])
    period = _period(args["period"])
    item_period, time_slot = _observation_period(period)
    values = payload["district_congestion"]
    dimensions = {"day_type": item_period.day_types[0], "time_slot": time_slot}
    observations = [
        MetricObservation(
            metric_name=metric_name,
            value=float(value),
            unit=unit,
            period=item_period,
            source=_source("get_district_congestion"),
            is_mock=True,
            dimensions=dimensions,
        ).model_dump(mode="json")
        for metric_name, value, unit in (
            ("district_congestion_density", values["persons_per_m2"], "persons/m2"),
            ("district_congestion_level", values["level"], "level_1_to_10"),
        )
    ]
    return _result(
        "get_district_congestion",
        {"area": area.model_dump(mode="json"), "observations": observations, "missing_data": []},
    )


def _visitors(args: Mapping[str, Any], payload: Mapping[str, Any]) -> ToolResult:
    area = _area(args["area"])
    period = _period(args["period"])
    target_age = cast(VisitorTargetAge, args["target_age"])
    age_group = _VISITOR_AGE_GROUPS[target_age]
    values = payload["visitor_demographics"]
    observations = [
        MetricObservation(
            metric_name="visitor_age_group_rate",
            value=float(values[f"{gender}_percent"]),
            unit="percent",
            period=period,
            source=_source("get_visitor_demographics"),
            is_mock=True,
            dimensions={"gender": gender, "age_group": age_group},
        ).model_dump(mode="json")
        for gender in ("male", "female")
    ]
    return _result(
        "get_visitor_demographics",
        {
            "area": area.model_dump(mode="json"),
            "target_age_group": age_group,
            "observations": observations,
            "missing_data": [],
        },
    )


def _competitors(args: Mapping[str, Any], payload: Mapping[str, Any]) -> ToolResult:
    area = _area(args["area"])
    radius_m = int(args["radius_m"])
    competitors = []
    for row in payload["competitors"]:
        if float(row["distance_m"]) <= radius_m:
            competitors.append(
                {
                    **row,
                    "latitude": area.latitude,
                    "longitude": area.longitude,
                }
            )
    return _result(
        "search_competitors",
        {
            "area": area.model_dump(mode="json"),
            "radius_m": radius_m,
            "retrieved_at": datetime.now().astimezone().isoformat(),
            "competitors": competitors,
        },
    )


def build_mock_result(tool_name: str, args: Mapping[str, Any]) -> ToolResult | None:
    """지원 Tool의 Mock 결과를 만들고, 지원하지 않거나 값이 없으면 None을 반환한다."""
    try:
        payload = _load_mock()
        builders = {
            "search_supported_districts": _search_supported_districts,
            "resolve_area_entities": _resolve_area_entities,
            "get_academy_demand": _academy,
            "get_station_exit_traffic": _station_traffic,
            "get_district_congestion": _congestion,
            "get_visitor_demographics": _visitors,
            "search_competitors": _competitors,
        }
        builder = builders.get(tool_name)
        return None if builder is None else builder(args, payload)
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None


def mock_tool_call_provider(request: Any) -> ToolMessage | None:
    """LangChain ToolCallRequest를 같은 호출 ID의 Mock ToolMessage로 변환한다."""
    tool_call = getattr(request, "tool_call", None)
    if not isinstance(tool_call, Mapping):
        return None
    tool_name = tool_call.get("name")
    args = tool_call.get("args")
    if not isinstance(tool_name, str) or not isinstance(args, Mapping):
        return None
    result = build_mock_result(tool_name, args)
    if result is None:
        return None
    return ToolMessage(
        content=result.model_dump_json(),
        tool_call_id=str(tool_call.get("id") or "mock-tool-call"),
        name=tool_name,
    )
