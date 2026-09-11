from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from models.schemas import AnalysisPeriod, ErrorCode, NearbyStation, StationTrafficData
from tools import subway_tools
from tools.subway_tools import (
    SubwayAuthError,
    SubwayInputError,
    SubwayRateLimitError,
    SubwayResponseError,
    SubwayUpstreamError,
    _fetch_station_exit_traffic,
    _parse_station_exit_traffic,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_parse_success_response() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")

    result = _parse_station_exit_traffic(payload, "221")

    assert result["station_id"] == "221"
    assert len(result["observations"]) == 3
    first = result["observations"][0]
    assert first["metric_name"] == "station_exit_user_count"
    assert first["value"] == 15.0
    assert first["unit"] == "persons/hour"
    assert first["dimensions"] == {
        "exit_number": "1",
        "day_type": "weekday",
        "time_slot": "05:00-06:00",
    }
    assert first["period"]["start_date"] == "2026-09-10"
    StationTrafficData.model_validate(result)


def test_zero_user_count_is_not_missing() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")

    result = _parse_station_exit_traffic(payload, "221")

    zero_observation = result["observations"][2]
    assert zero_observation["value"] == 0.0
    assert zero_observation["missing_reason"] is None


def test_identical_raw_observation_is_not_duplicated() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")
    payload["contents"]["raw"].append(payload["contents"]["raw"][0].copy())

    result = _parse_station_exit_traffic(payload, "221")

    assert len(result["observations"]) == 3


def test_empty_raw_is_successful_empty_result() -> None:
    payload = _load_fixture("subway_exit_traffic_empty.json")

    result = _parse_station_exit_traffic(payload, "221")

    assert result["observations"] == []
    assert result["missing_data"]
    StationTrafficData.model_validate(result)


def test_provider_failure_status_preserves_code() -> None:
    payload = _load_fixture("subway_exit_traffic_error.json")

    with pytest.raises(SubwayUpstreamError) as exc_info:
        _parse_station_exit_traffic(payload, "221")

    assert exc_info.value.error_code == "NO_DATA"


def test_response_station_must_match_request() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")

    with pytest.raises(SubwayResponseError) as exc_info:
        _parse_station_exit_traffic(payload, "222")

    assert exc_info.value.error_code == ErrorCode.API_RESPONSE_ERROR


def test_invalid_datetime_is_rejected() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")
    payload["contents"]["raw"][0]["datetime"] = "20261399050000"

    with pytest.raises(SubwayResponseError):
        _parse_station_exit_traffic(payload, "221")


@pytest.mark.parametrize("station_id", ["", "2", "221-", "abc", "221-RR"])
def test_invalid_station_id_stops_before_external_request(station_id: str) -> None:
    calls = 0

    def opener(*args: object, **kwargs: object) -> _FakeResponse:
        nonlocal calls
        calls += 1
        return _FakeResponse({})

    with pytest.raises(SubwayInputError):
        _fetch_station_exit_traffic(
            station_id,
            "latest",
            api_key="test-key",
            opener=opener,
        )

    assert calls == 0


def test_fetch_makes_one_request_without_key_in_url() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")
    captured = []

    def opener(request: object, *, timeout: float) -> _FakeResponse:
        captured.append((request, timeout))
        return _FakeResponse(payload)

    result = _fetch_station_exit_traffic(
        "221",
        "20260910",
        timeout=3.0,
        api_key="test-key",
        opener=opener,
    )

    assert result == payload
    assert len(captured) == 1
    request, timeout = captured[0]
    assert timeout == 3.0
    assert "test-key" not in request.full_url
    assert request.get_header("Appkey") == "test-key"
    assert "gender=all" in request.full_url
    assert "ageGrp=all" in request.full_url
    assert "date=20260910" in request.full_url


@pytest.mark.parametrize(
    ("http_status", "expected_exception", "expected_code"),
    [
        (401, SubwayAuthError, ErrorCode.API_AUTH_ERROR),
        (403, SubwayAuthError, ErrorCode.API_AUTH_ERROR),
        (429, SubwayRateLimitError, ErrorCode.API_RATE_LIMIT),
        (500, SubwayUpstreamError, ErrorCode.API_RESPONSE_ERROR),
    ],
)
def test_fetch_classifies_http_errors(
    http_status: int,
    expected_exception: type[Exception],
    expected_code: str,
) -> None:
    def opener(*args: object, **kwargs: object) -> _FakeResponse:
        raise HTTPError(
            url="https://apis.openapi.sk.com/sanitized",
            code=http_status,
            msg="error",
            hdrs=None,
            fp=None,
        )

    with pytest.raises(expected_exception) as exc_info:
        _fetch_station_exit_traffic(
            "221",
            "latest",
            api_key="test-key",
            opener=opener,
        )

    assert exc_info.value.error_code == expected_code


def test_fetch_rejects_invalid_json() -> None:
    class InvalidJsonResponse(_FakeResponse):
        def read(self) -> bytes:
            return b"not-json"

    with pytest.raises(SubwayResponseError) as exc_info:
        _fetch_station_exit_traffic(
            "221",
            "latest",
            api_key="test-key",
            opener=lambda *args, **kwargs: InvalidJsonResponse({}),
        )

    assert exc_info.value.error_code == ErrorCode.API_RESPONSE_ERROR


def test_public_tool_returns_common_model(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")
    monkeypatch.setattr(subway_tools, "_fetch_station_exit_traffic", lambda *args, **kwargs: payload)
    period = AnalysisPeriod(
        start_date="2026-09-10",
        end_date="2026-09-10",
        day_types=["weekday"],
        start_time="05:00",
        end_time="07:00",
    )

    result = subway_tools.get_station_exit_traffic("221", period)

    assert result.success is True
    assert result.error_code is None
    assert result.is_mock is False
    data = StationTrafficData.model_validate(result.data)
    assert len(data.observations) == 3


def test_public_tool_maps_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> dict:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(subway_tools, "_fetch_station_exit_traffic", fail)
    period = AnalysisPeriod(
        start_date="2026-09-10",
        end_date="2026-09-10",
        day_types=["weekday"],
    )

    result = subway_tools.get_station_exit_traffic("221", period)

    assert result.success is False
    assert result.error_code == ErrorCode.TOOL_INTERNAL_ERROR
    assert "secret" not in result.error_message


def test_find_nearby_stations_returns_nearest_station() -> None:
    result = subway_tools.find_nearby_stations(37.500622, 127.036456, 100)

    assert result.success is True
    assert result.is_mock is False
    stations = [NearbyStation.model_validate(item) for item in result.data]
    assert stations[0].station_id == "221"
    assert stations[0].station_name == "역삼역"
    assert stations[0].distance_m == 0


def test_find_nearby_stations_sorts_by_distance(monkeypatch: pytest.MonkeyPatch) -> None:
    stations = [
        NearbyStation(
            station_id="222",
            station_name="먼역",
            latitude=37.501,
            longitude=127.0,
            distance_m=0,
        ),
        NearbyStation(
            station_id="221",
            station_name="가까운역",
            latitude=37.5,
            longitude=127.0,
            distance_m=0,
        ),
    ]
    monkeypatch.setattr(subway_tools, "_load_station_reference", lambda: stations)

    result = subway_tools.find_nearby_stations(37.5, 127.0, 1_000)

    assert result.success is True
    assert [item["station_id"] for item in result.data] == ["221", "222"]


def test_find_nearby_stations_returns_contract_errors() -> None:
    invalid = subway_tools.find_nearby_stations("37.5", 127.0, 500)
    missing = subway_tools.find_nearby_stations(0.0, 0.0, 500)

    assert invalid.error_code == ErrorCode.INVALID_INPUT
    assert missing.error_code == ErrorCode.STATION_NOT_FOUND


def test_find_nearby_stations_handles_reference_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> list[NearbyStation]:
        raise SubwayResponseError("internal path", ErrorCode.TOOL_INTERNAL_ERROR)

    monkeypatch.setattr(subway_tools, "_load_station_reference", fail)

    result = subway_tools.find_nearby_stations(37.5, 127.0, 500)

    assert result.success is False
    assert result.error_code == ErrorCode.TOOL_INTERNAL_ERROR
    assert "internal path" in result.error_message


@pytest.mark.parametrize("station_id", ["221", "211-R", "D07", "P142", "P144-1"])
def test_supported_station_id_formats(station_id: str) -> None:
    assert subway_tools._validate_station_id(station_id) == station_id
