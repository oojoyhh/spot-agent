from datetime import date
import json
from urllib.error import HTTPError

import pytest

import tools.market_tools as market_tools
from models.schemas import AnalysisPeriod, AreaIdentity, ErrorCode, MetricObservation


class _FakeResponse:
    def __init__(self, payload: dict | bytes) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _area(*, located: bool = False) -> AreaIdentity:
    return AreaIdentity(
        commercial_area_id="9307",
        administrative_code=None,
        area_name="역삼역남부 3번출구",
        latitude=37.500692 if located else None,
        longitude=127.036978 if located else None,
    )


def _period() -> AnalysisPeriod:
    return AnalysisPeriod(
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 10),
        day_types=["weekday"],
        start_time="18:00",
        end_time="20:00",
    )


def test_search_and_resolve_enrich_verified_area(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        market_tools,
        "_fetch_areas",
        lambda: [
            {"areaId": "9307", "areaName": "역삼역남부 3번출구"},
            {"areaId": "9195", "areaName": "명동"},
        ],
    )

    searched = market_tools.search_supported_districts("역삼역")
    resolved = market_tools.resolve_area_entities("9307")

    assert searched.success and len(searched.data) == 1
    assert resolved.success
    assert resolved.data["administrative_code"] == "1168010100"
    assert resolved.data["latitude"] == pytest.approx(37.50012959)
    assert resolved.data["longitude"] == pytest.approx(127.03529551)


def test_search_uses_verified_region_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        market_tools,
        "_fetch_areas",
        lambda: [
            {"areaId": "9307", "areaName": "역삼역남부 3번출구"},
            {"areaId": "9195", "areaName": "명동"},
        ],
    )

    result = market_tools.search_supported_districts("강남구")

    assert result.success
    assert [area["commercial_area_id"] for area in result.data] == ["9307"]


def test_reference_name_mismatch_is_not_enriched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        market_tools,
        "_fetch_areas",
        lambda: [{"areaId": "9307", "areaName": "변경된 상권명"}],
    )

    result = market_tools.resolve_area_entities("9307")

    assert result.success
    assert result.data["administrative_code"] is None
    assert result.data["latitude"] is None


def test_congestion_preserves_density_level_and_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "status": {"code": "00"},
        "contents": {
            "areaId": "9307",
            "areaName": "역삼역남부 3번출구",
            "raw": [{"congestion": 0.04, "congestionLevel": 8, "datetime": "20260910180000"}],
        },
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.get_district_congestion(_area(), _period())

    assert result.success is True
    observations = [MetricObservation.model_validate(item) for item in result.data["observations"]]
    assert [(item.metric_name, item.value) for item in observations] == [
        ("district_congestion_density", 0.04),
        ("district_congestion_level", 8.0),
    ]
    assert observations[0].dimensions["time_slot"] == "18:00-19:00"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("datetime", "20260911180000"),
        ("datetime", "20260910183000"),
        ("congestion", True),
        ("congestion", float("nan")),
        ("congestionLevel", 8.5),
    ],
)
def test_invalid_congestion_row_is_response_error(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    payload = {
        "status": {"code": "00"},
        "contents": {
            "areaId": "9307",
            "raw": [{"congestion": 0.04, "congestionLevel": 8, "datetime": "20260910180000"}],
        },
    }
    payload["contents"]["raw"][0][field] = value
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.get_district_congestion(_area(), _period())

    assert result.error_code == ErrorCode.API_RESPONSE_ERROR


def test_holiday_congestion_is_not_relabeled_from_an_ordinary_weekday(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "status": {"code": "00"},
        "contents": {
            "areaId": "9307",
            "raw": [{"congestion": 0.04, "congestionLevel": 8, "datetime": "20260910180000"}],
        },
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)
    period = AnalysisPeriod(start_date="2026-09-10", end_date="2026-09-10", day_types=["holiday"])

    result = market_tools.get_district_congestion(_area(), period)

    assert result.success
    assert result.data["observations"] == []


def test_holiday_congestion_uses_holiday_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "status": {"code": "00"},
        "contents": {
            "areaId": "9307",
            "raw": [{"congestion": 0.04, "congestionLevel": 8, "datetime": "20261009180000"}],
        },
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)
    period = AnalysisPeriod(start_date="2026-10-09", end_date="2026-10-09", day_types=["holiday"])

    result = market_tools.get_district_congestion(_area(), period)

    assert result.success
    observations = [MetricObservation.model_validate(item) for item in result.data["observations"]]
    assert {item.dimensions["day_type"] for item in observations} == {"holiday"}


def test_visitors_select_target_age_and_keep_gender(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "status": {"code": "00"},
        "contents": {
            "areaId": "9307",
            "areaName": "역삼역남부 3번출구",
            "stat": [
                {"gender": "male", "ageGrp": "20", "rate": 12.5},
                {"gender": "female", "ageGrp": "20", "rate": 13.5},
                {"gender": "male", "ageGrp": "30", "rate": 10.0},
            ],
            "statStartDate": "20260812",
            "statEndDate": "20260910",
        },
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.get_visitor_demographics(_area(), "20대", _period())

    assert result.success is True
    assert result.data["target_age_group"] == "20"
    observations = [MetricObservation.model_validate(item) for item in result.data["observations"]]
    assert {item.dimensions["gender"] for item in observations} == {"male", "female"}
    assert sum(item.value for item in observations if item.value is not None) == 26.0


@pytest.mark.parametrize(
    "bad_row",
    [
        {"gender": "unknown", "ageGrp": "30", "rate": 10.0},
        {"gender": "male", "ageGrp": "unsupported", "rate": 10.0},
        {"gender": "male", "ageGrp": "30", "rate": 101.0},
        {"gender": "male", "ageGrp": "30", "rate": float("nan")},
    ],
)
def test_malformed_unselected_visitor_row_is_response_error(
    monkeypatch: pytest.MonkeyPatch,
    bad_row: dict,
) -> None:
    payload = {
        "status": {"code": "00"},
        "contents": {
            "areaId": "9307",
            "stat": [{"gender": "male", "ageGrp": "20", "rate": 12.5}, bad_row],
            "statStartDate": "20260812",
            "statEndDate": "20260910",
        },
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.get_visitor_demographics(_area(), "20대", _period())

    assert result.error_code == ErrorCode.API_RESPONSE_ERROR


def test_competitor_search_filters_exact_meter_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "searchPoiInfo": {
            "totalCount": "2",
            "count": "2",
            "page": "1",
            "pois": {
                "poi": [
                    {"id": "1", "name": "가까운 스터디카페", "radius": "0.4", "frontLat": "37.5", "frontLon": "127.0"},
                    {"id": "2", "name": "먼 스터디카페", "radius": "0.8", "frontLat": "37.6", "frontLon": "127.1"},
                ]
            },
        }
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.search_competitors(_area(located=True), 500)

    assert result.success is True
    assert [item["poi_id"] for item in result.data["competitors"]] == ["1"]
    assert result.data["competitors"][0]["distance_m"] == 400


def test_competitor_search_deduplicates_poi_id(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "searchPoiInfo": {
            "pois": {
                "poi": [
                    {"id": "1", "name": "스터디카페", "radius": "0.4", "frontLat": "37.5", "frontLon": "127.0"},
                    {"id": "1", "name": "스터디카페 입구", "radius": "0.3", "frontLat": "37.5", "frontLon": "127.0"},
                ]
            }
        }
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.search_competitors(_area(located=True), 500)

    assert result.success
    assert len(result.data["competitors"]) == 1
    assert result.data["competitors"][0]["distance_m"] == 300


@pytest.mark.parametrize(
    ("field", "value"),
    [("radius", "NaN"), ("radius", "-1"), ("frontLat", "91"), ("frontLon", "181")],
)
def test_invalid_competitor_poi_is_response_error(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    poi = {"id": "1", "name": "스터디카페", "radius": "0.4", "frontLat": "37.5", "frontLon": "127.0"}
    poi[field] = value
    payload = {"searchPoiInfo": {"pois": {"poi": [poi]}}}
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.search_competitors(_area(located=True), 500)

    assert result.error_code == ErrorCode.API_RESPONSE_ERROR


def test_competitor_search_requires_coordinates() -> None:
    result = market_tools.search_competitors(_area(), 500)

    assert result.error_code == ErrorCode.MISSING_REQUIRED_INPUT


def test_rent_and_closure_uses_editable_mock_file() -> None:
    result = market_tools.get_rent_and_closure_data(_area(), _period())

    assert result.success is True
    assert result.is_mock is True
    assert result.error_code is None
    observations = [MetricObservation.model_validate(item) for item in result.data["observations"]]
    assert {item.metric_name for item in observations} == {
        "deposit_krw",
        "monthly_rent_krw",
        "closure_rate_percent",
    }
    assert all(item.is_mock for item in observations)
    assert next(item.value for item in observations if item.metric_name == "monthly_rent_krw") == 2_600_000


def test_unknown_area_uses_default_rent_mock() -> None:
    unknown = AreaIdentity(
        commercial_area_id="unknown",
        administrative_code=None,
        area_name="Mock 상권",
        latitude=None,
        longitude=None,
    )

    result = market_tools.get_rent_and_closure_data(unknown, _period())

    observations = [MetricObservation.model_validate(item) for item in result.data["observations"]]
    assert next(item.value for item in observations if item.metric_name == "deposit_krw") == 30_000_000


def test_supported_area_no_match_is_not_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(market_tools, "_fetch_areas", lambda: [{"areaId": "9195", "areaName": "명동"}])

    result = market_tools.search_supported_districts("없는상권")

    assert result.success is False
    assert result.error_code == ErrorCode.AREA_NOT_FOUND
    assert result.data == []


@pytest.mark.parametrize(
    "contents",
    [
        [None],
        [{"areaId": "9307", "areaName": ""}],
        [
            {"areaId": "9307", "areaName": "역삼역남부 3번출구"},
            {"areaId": "9307", "areaName": "중복 상권"},
        ],
    ],
)
def test_malformed_area_list_is_response_error(
    monkeypatch: pytest.MonkeyPatch,
    contents: list,
) -> None:
    monkeypatch.setattr(
        market_tools,
        "_request_json",
        lambda *args, **kwargs: {"status": {"code": "00"}, "contents": contents},
    )

    result = market_tools.search_supported_districts("역삼")

    assert result.error_code == ErrorCode.API_RESPONSE_ERROR


def test_empty_congestion_is_success_with_missing_data(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "status": {"code": "00"},
        "contents": {"areaId": "9307", "areaName": "역삼", "raw": []},
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.get_district_congestion(_area(), _period())

    assert result.success is True
    assert result.data["observations"] == []
    assert result.data["missing_data"]


def test_empty_target_demographic_is_success_with_missing_data(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "status": {"code": "00"},
        "contents": {
            "areaId": "9307",
            "stat": [{"gender": "male", "ageGrp": "30", "rate": 10.0}],
            "statStartDate": "20260812",
            "statEndDate": "20260910",
        },
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.get_visitor_demographics(_area(), "20대", _period())

    assert result.success is True
    assert result.data["observations"] == []
    assert result.data["missing_data"]


def test_provider_age_code_is_not_accepted_as_user_target(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_request(*args: object, **kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(market_tools, "_request_json", fake_request)

    result = market_tools.get_visitor_demographics(_area(), "20", _period())  # type: ignore[arg-type]

    assert result.error_code == ErrorCode.INVALID_INPUT
    assert calls == 0


def test_empty_competitor_result_is_valid_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "searchPoiInfo": {
            "totalCount": "0",
            "count": "0",
            "page": "1",
            "pois": {"poi": []},
        }
    }
    monkeypatch.setattr(market_tools, "_request_json", lambda *args, **kwargs: payload)

    result = market_tools.search_competitors(_area(located=True), 500)

    assert result.success is True
    assert result.data["competitors"] == []


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ErrorCode.API_AUTH_ERROR),
        (403, ErrorCode.API_AUTH_ERROR),
        (429, ErrorCode.API_RATE_LIMIT),
        (400, ErrorCode.API_BAD_REQUEST),
        (500, ErrorCode.API_RESPONSE_ERROR),
    ],
)
def test_request_classifies_common_http_errors(status: int, code: ErrorCode) -> None:
    calls = 0

    def opener(*args: object, **kwargs: object) -> _FakeResponse:
        nonlocal calls
        calls += 1
        raise HTTPError("https://example.invalid", status, "error", None, None)

    with pytest.raises(market_tools.MarketApiError) as exc_info:
        market_tools._request_json("https://example.invalid", api_key="test-key", opener=opener)

    assert calls == 1
    assert exc_info.value.error_code == code


def test_request_rejects_invalid_json() -> None:
    with pytest.raises(market_tools.MarketApiError) as exc_info:
        market_tools._request_json(
            "https://example.invalid",
            api_key="test-key",
            opener=lambda *args, **kwargs: _FakeResponse(b"not-json"),
        )

    assert exc_info.value.error_code == ErrorCode.API_RESPONSE_ERROR


def test_invalid_timeout_stops_before_external_request() -> None:
    calls = 0

    def opener(*args: object, **kwargs: object) -> _FakeResponse:
        nonlocal calls
        calls += 1
        return _FakeResponse({})

    with pytest.raises(market_tools.MarketApiError) as exc_info:
        market_tools._request_json(
            "https://example.invalid",
            timeout=0,
            api_key="test-key",
            opener=opener,
        )

    assert calls == 0
    assert exc_info.value.error_code == ErrorCode.INVALID_INPUT


def test_invalid_rent_mock_returns_internal_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    path = tmp_path / "broken.json"
    path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(market_tools, "_RENT_MOCK_PATH", path)

    result = market_tools.get_rent_and_closure_data(_area(), _period())

    assert result.success is False
    assert result.error_code == ErrorCode.TOOL_INTERNAL_ERROR
