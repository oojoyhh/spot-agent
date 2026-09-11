"""StudySpot 지하철 API Tool.

재시도와 Mock fallback은 Middleware가 담당하며, 이 모듈은 호출당 외부 요청을
한 번만 수행한다.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from models.schemas import (
    AnalysisPeriod,
    ErrorCode,
    MetricObservation,
    NearbyStation,
    StationTrafficData,
    ToolResult,
)
from tools.calendar_utils import classify_day

__all__ = ["find_nearby_stations", "get_station_exit_traffic"]

_SOURCE = "SK Open API - 시간대별 지하철역 출구 통행자 수"
_STATION_SOURCE = "SK Open API 역 코드 + 서울시 역사마스터 좌표"
_EXIT_TRAFFIC_ENDPOINT = "https://apis.openapi.sk.com/puzzle/subway/exit/raw/hourly/stations"
_STATION_REFERENCE_PATH = Path(__file__).resolve().parents[1] / "data/reference/subway_stations.json"
_STATION_ID_PATTERN = re.compile(r"^[A-Z]?[0-9]{2,3}(?:-(?:[0-9]|R))?$")
_EARTH_RADIUS_M = 6_371_000


class SubwayApiError(Exception):
    """공통 오류 코드로 변환할 수 있는 지하철 API 오류."""

    def __init__(self, message: str, error_code: ErrorCode) -> None:
        super().__init__(message)
        self.error_code = error_code


class SubwayInputError(SubwayApiError):
    pass


class SubwayAuthError(SubwayApiError):
    pass


class SubwayRateLimitError(SubwayApiError):
    pass


class SubwayTimeoutError(SubwayApiError):
    pass


class SubwayUpstreamError(SubwayApiError):
    pass


class SubwayResponseError(SubwayApiError):
    pass


def _validate_station_id(station_id: str) -> str:
    if not isinstance(station_id, str):
        raise SubwayInputError("station_id는 문자열이어야 합니다.", ErrorCode.INVALID_INPUT)
    station_id = station_id.strip()
    if not _STATION_ID_PATTERN.fullmatch(station_id):
        raise SubwayInputError("station_id 형식이 올바르지 않습니다.", ErrorCode.INVALID_INPUT)
    return station_id


def _validate_query_date(query_date: str) -> str:
    if query_date == "latest":
        return query_date
    try:
        datetime.strptime(query_date, "%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise SubwayInputError("조회일은 YYYYMMDD 형식이어야 합니다.", ErrorCode.INVALID_INPUT) from exc
    return query_date


def _get_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("SK_OPEN_API_KEY")
    if not api_key:
        raise SubwayAuthError("SK_OPEN_API_KEY가 설정되지 않았습니다.", ErrorCode.API_AUTH_ERROR)
    return api_key


def _raise_for_http_error(error: HTTPError) -> None:
    if error.code in {401, 403}:
        raise SubwayAuthError("API 인증 또는 상품 권한을 확인해 주세요.", ErrorCode.API_AUTH_ERROR) from error
    if error.code == 429:
        raise SubwayRateLimitError("API 호출 한도를 초과했습니다.", ErrorCode.API_RATE_LIMIT) from error
    if error.code == 400:
        raise SubwayInputError("API 요청 파라미터가 올바르지 않습니다.", ErrorCode.API_BAD_REQUEST) from error
    if error.code == 404:
        raise SubwayInputError("해당 역을 찾을 수 없습니다.", ErrorCode.STATION_NOT_FOUND) from error
    raise SubwayUpstreamError("SK Open API 호출에 실패했습니다.", ErrorCode.API_RESPONSE_ERROR) from error


def _fetch_station_exit_traffic(
    station_id: str,
    query_date: str,
    *,
    timeout: float = 10.0,
    api_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """출구 통행량 원천 JSON을 한 번 조회한다."""
    station_id = _validate_station_id(station_id)
    query_date = _validate_query_date(query_date)
    if timeout <= 0:
        raise SubwayInputError("timeout은 0보다 커야 합니다.", ErrorCode.INVALID_INPUT)

    query = urlencode({"gender": "all", "ageGrp": "all", "date": query_date})
    request = Request(
        f"{_EXIT_TRAFFIC_ENDPOINT}/{station_id}?{query}",
        headers={"Accept": "application/json", "appKey": api_key or _get_api_key()},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        _raise_for_http_error(exc)
    except (TimeoutError, URLError) as exc:
        if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
            raise SubwayTimeoutError("API 요청 시간이 초과되었습니다.", ErrorCode.API_TIMEOUT) from exc
        raise SubwayUpstreamError("SK Open API에 연결할 수 없습니다.", ErrorCode.API_RESPONSE_ERROR) from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SubwayResponseError("API 응답이 올바른 JSON이 아닙니다.", ErrorCode.API_RESPONSE_ERROR) from exc
    if not isinstance(payload, dict):
        raise SubwayResponseError("API 응답 최상위 값이 객체가 아닙니다.", ErrorCode.API_RESPONSE_ERROR)
    return payload


def _required_string(container: dict[str, Any], field: str) -> str:
    value = container.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SubwayResponseError(f"응답의 {field} 값이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)
    return value


def _is_in_requested_time(observed_at: datetime, period: AnalysisPeriod) -> bool:
    if period.start_time is None:
        return True
    current = observed_at.strftime("%H:%M")
    if period.start_time < period.end_time:
        return period.start_time <= current < period.end_time
    return current >= period.start_time or current < period.end_time


def _parse_station_exit_traffic(
    payload: dict[str, Any],
    expected_station_id: str,
    period: AnalysisPeriod | None = None,
) -> StationTrafficData:
    """원천 응답을 검증된 ``StationTrafficData``로 정규화한다."""
    station_id = _validate_station_id(expected_station_id)
    status = payload.get("status")
    if not isinstance(status, dict):
        raise SubwayResponseError("응답에 status 객체가 없습니다.", ErrorCode.API_RESPONSE_ERROR)
    if status.get("code") != "00":
        code = ErrorCode.NO_DATA if status.get("code") == "NO_DATA" else ErrorCode.API_RESPONSE_ERROR
        raise SubwayUpstreamError("SK Open API가 실패 상태를 반환했습니다.", code)

    contents = payload.get("contents")
    if not isinstance(contents, dict):
        raise SubwayResponseError("응답에 contents 객체가 없습니다.", ErrorCode.API_RESPONSE_ERROR)
    if _required_string(contents, "stationCode") != station_id:
        raise SubwayResponseError("응답의 역 코드가 요청과 다릅니다.", ErrorCode.API_RESPONSE_ERROR)
    if _required_string(contents, "gender") != "all" or _required_string(contents, "ageGrp") != "all":
        raise SubwayResponseError("응답의 성별·연령 조건이 요청과 다릅니다.", ErrorCode.API_RESPONSE_ERROR)

    raw = contents.get("raw")
    if not isinstance(raw, list):
        raise SubwayResponseError("응답의 raw 값이 배열이 아닙니다.", ErrorCode.API_RESPONSE_ERROR)

    observations: list[MetricObservation] = []
    seen: dict[tuple[str, str], int] = {}
    for index, item in enumerate(raw):
        try:
            if not isinstance(item, dict):
                raise TypeError
            exit_number = _required_string(item, "exit")
            user_count = item["userCount"]
            observed_at = datetime.strptime(item["datetime"], "%Y%m%d%H%M%S")
            if isinstance(user_count, bool) or not isinstance(user_count, int) or user_count < 0:
                raise ValueError
            if observed_at.minute != 0 or observed_at.second != 0:
                raise ValueError
            if period is not None and observed_at.date() != period.start_date:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise SubwayResponseError(
                f"raw[{index}]의 필드 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR
            ) from exc

        unique_key = (exit_number, item["datetime"])
        if unique_key in seen:
            if seen[unique_key] != user_count:
                raise SubwayResponseError(
                    f"raw[{index}]에 값이 다른 중복 관측이 있습니다.", ErrorCode.API_RESPONSE_ERROR
                )
            continue
        seen[unique_key] = user_count

        day_type = classify_day(observed_at)
        if period is not None and (
            day_type not in period.day_types or not _is_in_requested_time(observed_at, period)
        ):
            continue

        end_at = observed_at + timedelta(hours=1)
        observation_period = AnalysisPeriod(
            start_date=observed_at.date(),
            end_date=observed_at.date(),
            timezone="Asia/Seoul",
            day_types=[day_type],
            start_time=observed_at.strftime("%H:%M"),
            end_time=end_at.strftime("%H:%M"),
        )
        observation = MetricObservation(
            metric_name="station_exit_user_count",
            value=float(user_count),
            unit="persons/hour",
            period=observation_period,
            source=_SOURCE,
            is_mock=False,
            dimensions={
                "exit_number": exit_number,
                "day_type": day_type,
                "time_slot": f"{observed_at:%H:%M}-{end_at:%H:%M}",
            },
        )
        observations.append(observation)

    return StationTrafficData(
        station_id=station_id,
        observations=observations,
        missing_data=[] if observations else ["조건에 맞는 출구 통행량 데이터가 없습니다."],
    )


def _failure(error_code: ErrorCode, message: str, source: str = _SOURCE) -> ToolResult:
    return ToolResult(
        success=False,
        source=source,
        data={},
        error_code=error_code,
        error_message=message,
        is_mock=False,
    )


def _load_station_reference(path: Path = _STATION_REFERENCE_PATH) -> list[NearbyStation]:
    """기준 JSON을 검증하고 거리 미포함 역 목록으로 읽는다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["stations"]
        if not isinstance(rows, list):
            raise TypeError

        stations = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError
            stations.append(
                NearbyStation(
                    station_id=row["station_id"],
                    station_name=row["station_name"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                    distance_m=0,
                )
            )
        return stations
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SubwayResponseError(
            "지하철역 기준 데이터를 읽을 수 없습니다.", ErrorCode.TOOL_INTERNAL_ERROR
        ) from exc


def _distance_m(latitude: float, longitude: float, station: NearbyStation) -> float:
    """두 WGS84 좌표 사이의 대권거리를 미터로 계산한다."""
    lat1, lat2 = math.radians(latitude), math.radians(station.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(station.longitude - longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(haversine))


def find_nearby_stations(latitude: float, longitude: float, radius_m: int) -> ToolResult:
    """로컬 기준 좌표에서 반경 내 SK 역 코드를 거리순으로 반환한다."""
    valid_coordinates = all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in (latitude, longitude)
    )
    if (
        not valid_coordinates
        or isinstance(radius_m, bool)
        or not isinstance(radius_m, int)
        or not all(math.isfinite(value) for value in (latitude, longitude, radius_m))
        or not (-90 <= latitude <= 90)
        or not (-180 <= longitude <= 180)
        or radius_m <= 0
    ):
        return _failure(ErrorCode.INVALID_INPUT, "좌표 또는 반경이 올바르지 않습니다.", _STATION_SOURCE)

    try:
        nearby: list[NearbyStation] = []
        for station in _load_station_reference():
            distance = _distance_m(float(latitude), float(longitude), station)
            if distance <= radius_m:
                nearby.append(station.model_copy(update={"distance_m": round(distance, 1)}))
        nearby.sort(key=lambda station: (station.distance_m, station.station_id))

        if not nearby:
            return _failure(
                ErrorCode.STATION_NOT_FOUND,
                "지정한 반경 안에서 지원 가능한 지하철역을 찾지 못했습니다.",
                _STATION_SOURCE,
            )
        return ToolResult(
            success=True,
            source=_STATION_SOURCE,
            data=[station.model_dump(mode="json") for station in nearby],
            error_code=None,
            error_message=None,
            is_mock=False,
        )
    except SubwayApiError as exc:
        return _failure(exc.error_code, str(exc), _STATION_SOURCE)
    except Exception:
        return _failure(
            ErrorCode.TOOL_INTERNAL_ERROR,
            "인근 지하철역 검색 중 오류가 발생했습니다.",
            _STATION_SOURCE,
        )


def get_station_exit_traffic(station_id: str, period: AnalysisPeriod) -> ToolResult:
    """한 역의 출구·시간대별 통행량을 공통 ToolResult로 반환한다."""
    try:
        if not isinstance(period, AnalysisPeriod):
            raise SubwayInputError("period는 AnalysisPeriod여야 합니다.", ErrorCode.INVALID_INPUT)
        if period.start_date != period.end_date:
            raise SubwayInputError("현재 API Tool은 하루 단위 조회만 지원합니다.", ErrorCode.INVALID_INPUT)

        station_id = _validate_station_id(station_id)
        payload = _fetch_station_exit_traffic(station_id, period.start_date.strftime("%Y%m%d"))
        data = _parse_station_exit_traffic(payload, station_id, period)
        return ToolResult(
            success=True,
            source=_SOURCE,
            data=data.model_dump(mode="json"),
            error_code=None,
            error_message=None,
            is_mock=False,
        )
    except SubwayApiError as exc:
        return _failure(exc.error_code, str(exc))
    except Exception:
        return _failure(ErrorCode.TOOL_INTERNAL_ERROR, "지하철 통행량 처리 중 오류가 발생했습니다.")
