from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

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
    assert result["station_name"] == "역삼역"
    assert result["subway_line"] == "2호선"
    assert len(result["observations"]) == 3
    assert result["observations"][0] == {
        "metric_name": "station_exit_user_count",
        "value": 15.0,
        "unit": "persons",
        "observed_at": "2026-09-10T05:00:00+09:00",
        "source": "SK Open API - 시간대별 지하철역 출구 통행자 수",
        "is_mock": False,
        "missing_reason": None,
        "dimensions": {
            "exit": "1",
            "time_slot": "05:00",
            "gender": "all",
            "age_group": "all",
        },
    }


def test_zero_user_count_is_not_missing() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")

    result = _parse_station_exit_traffic(payload, "221")

    zero_observation = result["observations"][2]
    assert zero_observation["value"] == 0.0
    assert zero_observation["missing_reason"] is None


def test_empty_raw_is_successful_empty_result() -> None:
    payload = _load_fixture("subway_exit_traffic_empty.json")

    result = _parse_station_exit_traffic(payload, "221")

    assert result["observations"] == []
    assert result["missing_data"] == []


def test_provider_failure_status_preserves_code() -> None:
    payload = _load_fixture("subway_exit_traffic_error.json")

    with pytest.raises(SubwayUpstreamError) as exc_info:
        _parse_station_exit_traffic(payload, "221")

    assert exc_info.value.error_code == "NO_DATA"


def test_response_station_must_match_request() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")

    with pytest.raises(SubwayResponseError) as exc_info:
        _parse_station_exit_traffic(payload, "222")

    assert exc_info.value.error_code == "INVALID_RESPONSE"


def test_invalid_datetime_is_rejected() -> None:
    payload = _load_fixture("subway_exit_traffic_success.json")
    payload["contents"]["raw"][0]["datetime"] = "20261399050000"

    with pytest.raises(SubwayResponseError):
        _parse_station_exit_traffic(payload, "221")


@pytest.mark.parametrize("station_id", ["", "22", "221-", "abc", "221-RR"])
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
        (401, SubwayAuthError, "AUTH_ERROR"),
        (403, SubwayAuthError, "AUTH_ERROR"),
        (429, SubwayRateLimitError, "RATE_LIMITED"),
        (500, SubwayUpstreamError, "UPSTREAM_ERROR"),
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

    assert exc_info.value.error_code == "INVALID_RESPONSE"
