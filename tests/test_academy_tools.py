from datetime import date
import json
from urllib.error import HTTPError

import pytest

import tools.academy_tools as academy_tools
from models.schemas import AcademyDemandData, AnalysisPeriod, AreaIdentity, ErrorCode


class _FakeResponse:
    def __init__(self, payload: dict | bytes) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _area(administrative_code: str | None = "1168010100") -> AreaIdentity:
    return AreaIdentity(
        commercial_area_id="9307",
        administrative_code=administrative_code,
        area_name="역삼역남부 3번출구",
        latitude=None,
        longitude=None,
    )


def _period() -> AnalysisPeriod:
    return AnalysisPeriod(
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 10),
        day_types=["weekday"],
    )


def _payload(stat: list[dict] | None = None) -> dict:
    return {
        "status": {"code": "00", "message": "success", "totalCount": 1},
        "contents": {
            "districtCode": "1168010100",
            "districtName": "서울특별시 강남구 역삼동",
            "category": "전체",
            "schoolAge": "고등학생",
            "stat": stat
            if stat is not None
            else [
                {
                    "ypId": "473863",
                    "ypName": "강남대성학원",
                    "category": "입시/고시",
                    "schoolAge": "고등학생",
                    "lat": 37.495853,
                    "lng": 127.03096,
                    "count": 1404,
                }
            ],
            "statStartDate": "20260812",
            "statEndDate": "20260910",
            "yearMonth": "202609",
        },
    }


def test_get_academy_demand_returns_common_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_request(district_code: str, school_age: str) -> dict:
        captured.update(district_code=district_code, school_age=school_age)
        return _payload()

    monkeypatch.setattr(academy_tools, "_request", fake_request)

    result = academy_tools.get_academy_demand(_area(), "고등학생", _period())

    assert result.success is True
    assert captured == {"district_code": "1168010100", "school_age": "high"}
    data = AcademyDemandData.model_validate(result.data)
    assert data.observations[0].value == 1404
    assert data.observations[0].dimensions["academy_id"] == "473863"
    assert data.observations[0].period.start_date == date(2026, 8, 12)


def test_empty_ranking_is_missing_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(academy_tools, "_request", lambda *args: _payload([]))

    result = academy_tools.get_academy_demand(_area(), "high", _period())

    data = AcademyDemandData.model_validate(result.data)
    assert result.success is True
    assert data.observations == []
    assert data.missing_data


def test_missing_district_code_stops_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_request(*args: object) -> dict:
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(academy_tools, "_request", fake_request)
    result = academy_tools.get_academy_demand(_area(None), "고등학생", _period())

    assert calls == 0
    assert result.error_code == ErrorCode.MISSING_REQUIRED_INPUT


def test_invalid_district_code_stops_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_request(*args: object) -> dict:
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(academy_tools, "_request", fake_request)
    result = academy_tools.get_academy_demand(_area("11680"), "고등학생", _period())

    assert calls == 0
    assert result.error_code == ErrorCode.INVALID_INPUT


def test_age_decade_is_not_guessed_as_school_age() -> None:
    result = academy_tools.get_academy_demand(_area(), "10대", _period())

    assert result.error_code == ErrorCode.INVALID_INPUT


def test_request_calls_external_api_once_without_key_in_url() -> None:
    captured = []

    def opener(request: object, *, timeout: float) -> _FakeResponse:
        captured.append((request, timeout))
        return _FakeResponse(_payload())

    result = academy_tools._request(
        "1168010100",
        "high",
        api_key="test-key",
        opener=opener,
    )

    assert result == _payload()
    assert len(captured) == 1
    request, _ = captured[0]
    assert "test-key" not in request.full_url
    assert request.get_header("Appkey") == "test-key"


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
    def opener(*args: object, **kwargs: object) -> _FakeResponse:
        raise HTTPError("https://example.invalid", status, "error", None, None)

    with pytest.raises(academy_tools.AcademyApiError) as exc_info:
        academy_tools._request("1168010100", "high", api_key="test-key", opener=opener)

    assert exc_info.value.error_code == code


def test_request_rejects_invalid_json() -> None:
    with pytest.raises(academy_tools.AcademyApiError) as exc_info:
        academy_tools._request(
            "1168010100",
            "high",
            api_key="test-key",
            opener=lambda *args, **kwargs: _FakeResponse(b"not-json"),
        )

    assert exc_info.value.error_code == ErrorCode.API_RESPONSE_ERROR


def test_response_district_code_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _payload()
    payload["contents"]["districtCode"] = "1111010100"
    monkeypatch.setattr(academy_tools, "_request", lambda *args: payload)

    result = academy_tools.get_academy_demand(_area(), "high", _period())

    assert result.error_code == ErrorCode.API_RESPONSE_ERROR
