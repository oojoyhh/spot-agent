"""지하철역 및 출구 통행량 API Tool.

담당: 역할 1 · 중우 · feature/api-tools
명세: docs/00_공통계약.md, docs/01_API_Tool.md

공통 Pydantic 모델이 합쳐지기 전에도 검증할 수 있도록 SK Open API 요청과
원천 응답 파싱은 공통 모델에 의존하지 않는 내부 함수로 분리한다.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

__all__ = ["find_nearby_stations", "get_station_exit_traffic"]

_EXIT_TRAFFIC_ENDPOINT = (
    "https://apis.openapi.sk.com/puzzle/subway/exit/raw/hourly/stations"
)
_STATION_ID_PATTERN = re.compile(r"^[0-9]{3}(?:-(?:[0-9]|R))?$")
_SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")


class SubwayApiError(Exception):
    """지하철 API 요청·응답 처리 중 발생한 기본 오류."""

    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class SubwayInputError(SubwayApiError):
    """외부 요청 전에 발견한 잘못된 입력."""


class SubwayAuthError(SubwayApiError):
    """API Key 누락 또는 인증·권한 오류."""


class SubwayRateLimitError(SubwayApiError):
    """호출 한도 초과 오류."""


class SubwayTimeoutError(SubwayApiError):
    """외부 API timeout 오류."""


class SubwayUpstreamError(SubwayApiError):
    """SK Open API 서버 또는 비정상 상태 응답 오류."""


class SubwayResponseError(SubwayApiError):
    """JSON 파싱 또는 응답 스키마 오류."""


def _validate_station_id(station_id: str) -> str:
    """공식 문서의 본선·지선·순환선 역 코드 형식을 검증한다."""
    if not isinstance(station_id, str):
        raise SubwayInputError(
            "station_id must be a string",
            error_code="INVALID_INPUT",
        )

    normalized = station_id.strip()
    if not _STATION_ID_PATTERN.fullmatch(normalized):
        raise SubwayInputError(
            "station_id must be a three-digit station code with an optional branch suffix",
            error_code="INVALID_INPUT",
        )
    return normalized


def _validate_query_date(date: str) -> str:
    """API의 ``latest`` 또는 ``YYYYMMDD`` 날짜 형식을 검증한다."""
    if not isinstance(date, str):
        raise SubwayInputError(
            "date must be a string",
            error_code="INVALID_INPUT",
        )

    normalized = date.strip()
    if normalized == "latest":
        return normalized

    try:
        datetime.strptime(normalized, "%Y%m%d")
    except ValueError as exc:
        raise SubwayInputError(
            "date must be 'latest' or a valid YYYYMMDD value",
            error_code="INVALID_INPUT",
        ) from exc
    return normalized


def _get_api_key() -> str:
    """환경변수에서 API Key를 읽되 오류 메시지에는 값을 포함하지 않는다."""
    load_dotenv()
    api_key = os.getenv("SK_OPEN_API_KEY")
    if not api_key:
        raise SubwayAuthError(
            "SK_OPEN_API_KEY is not configured",
            error_code="AUTH_ERROR",
        )
    return api_key


def _raise_for_http_error(error: HTTPError) -> None:
    """HTTP 상태를 공통 오류로 변환할 수 있는 내부 예외로 분류한다."""
    if error.code in {401, 403}:
        raise SubwayAuthError(
            "SK Open API authentication or product permission failed",
            error_code="AUTH_ERROR",
        ) from error
    if error.code == 429:
        raise SubwayRateLimitError(
            "SK Open API rate limit exceeded",
            error_code="RATE_LIMITED",
        ) from error
    raise SubwayUpstreamError(
        f"SK Open API returned HTTP {error.code}",
        error_code="UPSTREAM_ERROR",
    ) from error


def _fetch_station_exit_traffic(
    station_id: str,
    date: str,
    *,
    timeout: float = 10.0,
    api_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """SK Open API를 한 번 호출해 원천 JSON 객체를 반환한다.

    재시도는 Guardrail·Middleware 담당이므로 이 함수에서는 수행하지 않는다.
    ``opener``와 ``api_key`` 인자는 네트워크 없는 단위 테스트를 위한 주입점이다.
    """
    normalized_station_id = _validate_station_id(station_id)
    normalized_date = _validate_query_date(date)
    if timeout <= 0:
        raise SubwayInputError(
            "timeout must be greater than zero",
            error_code="INVALID_INPUT",
        )

    query = urlencode(
        {
            "gender": "all",
            "ageGrp": "all",
            "date": normalized_date,
        }
    )
    url = f"{_EXIT_TRAFFIC_ENDPOINT}/{normalized_station_id}?{query}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "appKey": api_key or _get_api_key(),
        },
        method="GET",
    )

    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        _raise_for_http_error(exc)
    except TimeoutError as exc:
        raise SubwayTimeoutError(
            "SK Open API request timed out",
            error_code="TIMEOUT",
        ) from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise SubwayTimeoutError(
                "SK Open API request timed out",
                error_code="TIMEOUT",
            ) from exc
        raise SubwayUpstreamError(
            "SK Open API request failed",
            error_code="UPSTREAM_ERROR",
        ) from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SubwayResponseError(
            "SK Open API response is not valid UTF-8 JSON",
            error_code="INVALID_RESPONSE",
        ) from exc

    if not isinstance(payload, dict):
        raise SubwayResponseError(
            "SK Open API response root must be an object",
            error_code="INVALID_RESPONSE",
        )
    return payload


def _required_string(container: dict[str, Any], field: str) -> str:
    value = container.get(field)
    if not isinstance(value, str) or not value:
        raise SubwayResponseError(
            f"response field '{field}' must be a non-empty string",
            error_code="INVALID_RESPONSE",
        )
    return value


def _parse_station_exit_traffic(
    payload: dict[str, Any],
    expected_station_id: str,
) -> dict[str, Any]:
    """원천 응답을 공통 모델 직전의 중간 자료구조로 정규화한다."""
    normalized_station_id = _validate_station_id(expected_station_id)
    if not isinstance(payload, dict):
        raise SubwayResponseError(
            "response root must be an object",
            error_code="INVALID_RESPONSE",
        )

    status = payload.get("status")
    if not isinstance(status, dict):
        raise SubwayResponseError(
            "response field 'status' must be an object",
            error_code="INVALID_RESPONSE",
        )
    status_code = status.get("code")
    if status_code != "00":
        upstream_code = status_code if isinstance(status_code, str) else "UNKNOWN"
        raise SubwayUpstreamError(
            f"SK Open API returned failure status '{upstream_code}'",
            error_code=upstream_code,
        )

    contents = payload.get("contents")
    if not isinstance(contents, dict):
        raise SubwayResponseError(
            "response field 'contents' must be an object",
            error_code="INVALID_RESPONSE",
        )

    station_code = _required_string(contents, "stationCode")
    if station_code != normalized_station_id:
        raise SubwayResponseError(
            "response stationCode does not match the requested station_id",
            error_code="INVALID_RESPONSE",
        )

    station_name = _required_string(contents, "stationName")
    subway_line = _required_string(contents, "subwayLine")
    gender = _required_string(contents, "gender")
    age_group = _required_string(contents, "ageGrp")
    raw = contents.get("raw")
    if not isinstance(raw, list):
        raise SubwayResponseError(
            "response field 'raw' must be an array",
            error_code="INVALID_RESPONSE",
        )

    observations: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SubwayResponseError(
                f"raw[{index}] must be an object",
                error_code="INVALID_RESPONSE",
            )

        exit_number = _required_string(item, "exit")
        user_count = item.get("userCount")
        if isinstance(user_count, bool) or not isinstance(user_count, int):
            raise SubwayResponseError(
                f"raw[{index}].userCount must be an integer",
                error_code="INVALID_RESPONSE",
            )
        if user_count < 0:
            raise SubwayResponseError(
                f"raw[{index}].userCount must not be negative",
                error_code="INVALID_RESPONSE",
            )

        raw_datetime = _required_string(item, "datetime")
        try:
            observed_at = datetime.strptime(raw_datetime, "%Y%m%d%H%M%S").replace(
                tzinfo=_SEOUL_TIMEZONE
            )
        except ValueError as exc:
            raise SubwayResponseError(
                f"raw[{index}].datetime must be a valid YYYYMMDDHHMMSS value",
                error_code="INVALID_RESPONSE",
            ) from exc

        observations.append(
            {
                "metric_name": "station_exit_user_count",
                "value": float(user_count),
                "unit": "persons",
                "observed_at": observed_at.isoformat(),
                "source": "SK Open API - 시간대별 지하철역 출구 통행자 수",
                "is_mock": False,
                "missing_reason": None,
                "dimensions": {
                    "exit": exit_number,
                    "time_slot": observed_at.strftime("%H:%M"),
                    "gender": gender,
                    "age_group": age_group,
                },
            }
        )

    return {
        "station_id": station_code,
        "station_name": station_name,
        "subway_line": subway_line,
        "gender": gender,
        "age_group": age_group,
        "observations": observations,
        "missing_data": [],
    }


def find_nearby_stations(
    latitude: float,
    longitude: float,
    radius_m: int,
) -> "ToolResult":
    """좌표와 반경을 기준으로 ``NearbyStation`` 목록을 조회한다.

    위도·경도와 양수 반경을 검증하고, 반환한 ``station_id``의 코드
    체계를 후속 출구 통행량 조회에서도 그대로 사용해야 한다.
    """
    raise NotImplementedError("find_nearby_stations API adapter is not implemented")


def get_station_exit_traffic(
    station_id: str,
    period: "AnalysisPeriod",
) -> "ToolResult":
    """역 ID와 분석 기간으로 출구별 통행량을 조회한다.

    출구·시간대별 데이터의 집계 단위와 중복 제거 기준을 보존해
    ``StationTrafficData`` 직렬화 사전을 반환해야 한다.
    """
    raise NotImplementedError(
        "common ToolResult, AnalysisPeriod, MetricObservation, and "
        "StationTrafficData models are not available yet"
    )
