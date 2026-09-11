"""지원 상권·혼잡도·방문자·경쟁점포 API Tool."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from models.schemas import AnalysisPeriod, AreaIdentity, DayType, ErrorCode, MetricObservation, ToolResult
from tools.api_types import VisitorTargetAge
from tools.calendar_utils import classify_day

__all__ = [
    "search_supported_districts",
    "resolve_area_entities",
    "get_district_congestion",
    "get_visitor_demographics",
    "search_competitors",
    "get_rent_and_closure_data",
]

_AREAS_SOURCE = "SK Open API - 데이터 제공 가능 상권; TMAP - 검증된 출구 위치"
_CONGESTION_SOURCE = "SK Open API - 시간대별 상권 혼잡도"
_VISITOR_SOURCE = "SK Open API - 상권 방문자 연령 분포"
_COMPETITOR_SOURCE = "TMAP - 장소 통합 검색"
_AREAS_ENDPOINT = "https://apis.openapi.sk.com/puzzle/place/meta/areas"
_CONGESTION_ENDPOINT = "https://apis.openapi.sk.com/puzzle/place/congestion/stat/raw/hourly/areas"
_VISITOR_ENDPOINT = "https://apis.openapi.sk.com/puzzle/place/visit/seg/stat/daily/areas"
_POI_ENDPOINT = "https://apis.openapi.sk.com/tmap/pois"
_AREA_REFERENCE_PATH = Path(__file__).resolve().parents[1] / "data" / "reference" / "commercial_areas.json"
_RENT_MOCK_PATH = Path(__file__).resolve().parents[1] / "data" / "mock" / "rent_and_closure.json"
_AGE_GROUPS: dict[VisitorTargetAge, str] = {
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


@dataclass(frozen=True, slots=True)
class AreaReference:
    area: AreaIdentity
    aliases: tuple[str, ...]


class MarketApiError(Exception):
    def __init__(self, message: str, error_code: ErrorCode) -> None:
        super().__init__(message)
        self.error_code = error_code


def _failure(
    source: str,
    code: ErrorCode,
    message: str,
    *,
    data: dict[str, Any] | list[Any] | None = None,
) -> ToolResult:
    return ToolResult(
        success=False,
        source=source,
        data={} if data is None else data,
        error_code=code,
        error_message=message,
        is_mock=False,
    )


def _api_key() -> str:
    load_dotenv()
    key = os.getenv("SK_OPEN_API_KEY")
    if not key:
        raise MarketApiError("SK_OPEN_API_KEY가 설정되지 않았습니다.", ErrorCode.API_AUTH_ERROR)
    return key


def _request_json(
    endpoint: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
    api_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    if timeout <= 0:
        raise MarketApiError("timeout은 0보다 커야 합니다.", ErrorCode.INVALID_INPUT)
    url = endpoint + (f"?{urlencode(params)}" if params else "")
    request = Request(
        url,
        headers={"Accept": "application/json", "appKey": api_key or _api_key()},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise MarketApiError("API 인증 또는 상품 권한을 확인해 주세요.", ErrorCode.API_AUTH_ERROR) from exc
        if exc.code == 429:
            raise MarketApiError("API 호출 한도를 초과했습니다.", ErrorCode.API_RATE_LIMIT) from exc
        if exc.code == 400:
            raise MarketApiError("API 요청 파라미터가 올바르지 않습니다.", ErrorCode.API_BAD_REQUEST) from exc
        raise MarketApiError("외부 API 호출에 실패했습니다.", ErrorCode.API_RESPONSE_ERROR) from exc
    except (TimeoutError, URLError) as exc:
        if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
            raise MarketApiError("API 요청 시간이 초과되었습니다.", ErrorCode.API_TIMEOUT) from exc
        raise MarketApiError("외부 API에 연결할 수 없습니다.", ErrorCode.API_RESPONSE_ERROR) from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketApiError("API 응답이 올바른 JSON이 아닙니다.", ErrorCode.API_RESPONSE_ERROR) from exc
    if not isinstance(payload, dict):
        raise MarketApiError("API 응답 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)
    return payload


def _sk_contents(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    if not isinstance(status, dict) or status.get("code") != "00":
        code = ErrorCode.NO_DATA if isinstance(status, dict) and status.get("code") == "NO_DATA" else ErrorCode.API_RESPONSE_ERROR
        raise MarketApiError("SK Open API가 실패 상태를 반환했습니다.", code)
    contents = payload.get("contents")
    if not isinstance(contents, dict):
        raise MarketApiError("응답에 contents 객체가 없습니다.", ErrorCode.API_RESPONSE_ERROR)
    return contents


def _area(area: AreaIdentity) -> AreaIdentity:
    if not isinstance(area, AreaIdentity):
        raise MarketApiError("area 형식이 올바르지 않습니다.", ErrorCode.INVALID_INPUT)
    return area


def _day_type(moment: datetime, period: AnalysisPeriod) -> DayType | None:
    classified = classify_day(moment)
    return classified if classified in period.day_types else None


def _in_time(moment: datetime, period: AnalysisPeriod) -> bool:
    if period.start_time is None:
        return True
    current = moment.strftime("%H:%M")
    if period.start_time < period.end_time:
        return period.start_time <= current < period.end_time
    return current >= period.start_time or current < period.end_time


def _observation_period(moment: datetime, day_type: DayType) -> tuple[AnalysisPeriod, str]:
    end = moment + timedelta(hours=1)
    time_slot = f"{moment:%H:%M}-{end:%H:%M}"
    return (
        AnalysisPeriod(
            start_date=moment.date(),
            end_date=moment.date(),
            day_types=[day_type],
            start_time=moment.strftime("%H:%M"),
            end_time=end.strftime("%H:%M"),
        ),
        time_slot,
    )


def _fetch_areas() -> list[dict[str, Any]]:
    payload = _request_json(_AREAS_ENDPOINT, {"offset": 0, "limit": 1000})
    status = payload.get("status")
    contents = payload.get("contents")
    if not isinstance(status, dict) or status.get("code") != "00" or not isinstance(contents, list):
        raise MarketApiError("상권 목록 응답 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)
    area_ids: set[str] = set()
    for index, item in enumerate(contents):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("areaId"), str)
            or not item["areaId"].strip()
            or not isinstance(item.get("areaName"), str)
            or not item["areaName"].strip()
            or item["areaId"] in area_ids
        ):
            raise MarketApiError(f"상권 목록의 contents[{index}] 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)
        area_ids.add(item["areaId"])
    return contents


def _load_area_references() -> dict[str, AreaReference]:
    try:
        payload = json.loads(_AREA_REFERENCE_PATH.read_text(encoding="utf-8"))
        items = payload["areas"]
        if not isinstance(items, list):
            raise TypeError
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise MarketApiError("상권 기준 데이터를 읽을 수 없습니다.", ErrorCode.TOOL_INTERNAL_ERROR) from exc

    references: dict[str, AreaReference] = {}
    try:
        for item in items:
            area = AreaIdentity.model_validate(item["area"])
            aliases = item.get("aliases", [])
            if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias.strip() for alias in aliases):
                raise ValueError
            if area.commercial_area_id in references:
                raise ValueError
            references[area.commercial_area_id] = AreaReference(
                area=area,
                aliases=tuple(cast(list[str], aliases)),
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketApiError("상권 기준 데이터 형식이 올바르지 않습니다.", ErrorCode.TOOL_INTERNAL_ERROR) from exc
    return references


def _area_identity(item: dict[str, Any], references: dict[str, AreaReference]) -> AreaIdentity:
    try:
        area = AreaIdentity(
            commercial_area_id=item["areaId"],
            administrative_code=None,
            area_name=item["areaName"],
            latitude=None,
            longitude=None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketApiError("상권 목록 항목의 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR) from exc

    reference = references.get(area.commercial_area_id)
    if reference is not None and reference.area.area_name == area.area_name:
        return reference.area
    return area


def search_supported_districts(preferred_region: str) -> ToolResult:
    """상권명 또는 검증된 지역 별칭에 희망 지역 문자열이 포함된 지원 상권을 반환한다."""
    try:
        if not isinstance(preferred_region, str) or not preferred_region.strip():
            raise MarketApiError("preferred_region이 비어 있습니다.", ErrorCode.INVALID_INPUT)
        keyword = "".join(preferred_region.split()).casefold()
        references = _load_area_references()
        areas: list[AreaIdentity] = []
        for item in _fetch_areas():
            if not isinstance(item, dict):
                continue
            area = _area_identity(item, references)
            reference = references.get(area.commercial_area_id)
            searchable = [area.area_name, *(reference.aliases if reference is not None else ())]
            if any(keyword in "".join(value.split()).casefold() for value in searchable):
                areas.append(area)
        if not areas:
            return _failure(_AREAS_SOURCE, ErrorCode.AREA_NOT_FOUND, "지원 상권을 찾지 못했습니다.", data=[])
        return ToolResult(
            success=True,
            source=_AREAS_SOURCE,
            data=[area.model_dump(mode="json") for area in areas],
            error_code=None,
            error_message=None,
            is_mock=False,
        )
    except MarketApiError as exc:
        return _failure(_AREAS_SOURCE, exc.error_code, str(exc), data=[])
    except Exception:
        return _failure(_AREAS_SOURCE, ErrorCode.TOOL_INTERNAL_ERROR, "지원 상권 처리 중 오류가 발생했습니다.", data=[])


def resolve_area_entities(selected_candidate_id: str) -> ToolResult:
    """상권 ID를 해석하고 검증된 기준 데이터가 있을 때만 코드·출구 좌표를 보완한다."""
    try:
        if not isinstance(selected_candidate_id, str) or not selected_candidate_id.strip():
            raise MarketApiError("selected_candidate_id가 비어 있습니다.", ErrorCode.INVALID_INPUT)
        candidate_id = selected_candidate_id.strip()
        references = _load_area_references()
        match = next(
            (item for item in _fetch_areas() if isinstance(item, dict) and item.get("areaId") == candidate_id),
            None,
        )
        if match is None:
            return _failure(_AREAS_SOURCE, ErrorCode.AREA_NOT_FOUND, "지원 상권 ID를 찾지 못했습니다.")
        data = _area_identity(match, references)
        return ToolResult(
            success=True,
            source=_AREAS_SOURCE,
            data=data.model_dump(mode="json"),
            error_code=None,
            error_message=None,
            is_mock=False,
        )
    except MarketApiError as exc:
        return _failure(_AREAS_SOURCE, exc.error_code, str(exc))
    except Exception:
        return _failure(_AREAS_SOURCE, ErrorCode.TOOL_INTERNAL_ERROR, "상권 식별 처리 중 오류가 발생했습니다.")


def get_district_congestion(area: AreaIdentity, period: AnalysisPeriod) -> ToolResult:
    """상권의 시간대별 혼잡 밀도와 1~10 레벨을 조회한다."""
    try:
        area = _area(area)
        if not isinstance(period, AnalysisPeriod) or period.start_date != period.end_date:
            raise MarketApiError("혼잡도는 하루 단위 AnalysisPeriod로 조회해야 합니다.", ErrorCode.INVALID_INPUT)
        payload = _request_json(
            f"{_CONGESTION_ENDPOINT}/{area.commercial_area_id}",
            {"date": period.start_date.strftime("%Y%m%d")},
        )
        contents = _sk_contents(payload)
        if contents.get("areaId") != area.commercial_area_id or not isinstance(contents.get("raw"), list):
            raise MarketApiError("혼잡도 응답의 상권 ID 또는 raw가 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)

        observations: list[dict[str, Any]] = []
        seen: dict[str, tuple[float, int]] = {}
        for index, item in enumerate(contents["raw"]):
            try:
                if not isinstance(item, dict):
                    raise TypeError
                moment = datetime.strptime(item["datetime"], "%Y%m%d%H%M%S")
                congestion_value = item["congestion"]
                level = item["congestionLevel"]
                if (
                    isinstance(congestion_value, bool)
                    or not isinstance(congestion_value, (int, float))
                    or not math.isfinite(congestion_value)
                    or congestion_value < 0
                    or isinstance(level, bool)
                    or not isinstance(level, int)
                    or not 1 <= level <= 10
                    or moment.minute != 0
                    or moment.second != 0
                    or moment.date() != period.start_date
                ):
                    raise ValueError
                congestion = float(congestion_value)
            except (KeyError, TypeError, ValueError) as exc:
                raise MarketApiError(f"raw[{index}]의 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR) from exc
            raw_key = item["datetime"]
            raw_value = (congestion, level)
            if raw_key in seen:
                if seen[raw_key] != raw_value:
                    raise MarketApiError(f"raw[{index}]에 값이 다른 중복 관측이 있습니다.", ErrorCode.API_RESPONSE_ERROR)
                continue
            seen[raw_key] = raw_value
            day_type = _day_type(moment, period)
            if day_type is None or not _in_time(moment, period):
                continue
            item_period, time_slot = _observation_period(moment, day_type)
            dimensions = {"day_type": day_type, "time_slot": time_slot}
            for metric_name, value, unit in (
                ("district_congestion_density", congestion, "persons/m2"),
                ("district_congestion_level", float(level), "level_1_to_10"),
            ):
                observations.append(
                    MetricObservation(
                        metric_name=metric_name,
                        value=value,
                        unit=unit,
                        period=item_period,
                        source=_CONGESTION_SOURCE,
                        is_mock=False,
                        dimensions=dimensions,
                    ).model_dump(mode="json")
                )
        data = {
            "area": area.model_dump(mode="json"),
            "observations": observations,
            "missing_data": [] if observations else ["조건에 맞는 상권 혼잡도 데이터가 없습니다."],
        }
        return ToolResult(success=True, source=_CONGESTION_SOURCE, data=data, error_code=None, error_message=None, is_mock=False)
    except MarketApiError as exc:
        return _failure(_CONGESTION_SOURCE, exc.error_code, str(exc))
    except Exception:
        return _failure(_CONGESTION_SOURCE, ErrorCode.TOOL_INTERNAL_ERROR, "상권 혼잡도 처리 중 오류가 발생했습니다.")


def get_visitor_demographics(
    area: AreaIdentity,
    target_age: VisitorTargetAge,
    period: AnalysisPeriod,
) -> ToolResult:
    """상권 방문자 중 지정 연령대가 차지하는 성별 비율을 조회한다."""
    try:
        area = _area(area)
        if not isinstance(period, AnalysisPeriod):
            raise MarketApiError("period 형식이 올바르지 않습니다.", ErrorCode.INVALID_INPUT)
        if not isinstance(target_age, str) or target_age.strip() not in _AGE_GROUPS:
            raise MarketApiError("방문자 target_age는 10대·20대와 같은 연령대여야 합니다.", ErrorCode.INVALID_INPUT)
        normalized_target_age = cast(VisitorTargetAge, target_age.strip())
        age_group = _AGE_GROUPS[normalized_target_age]
        contents = _sk_contents(_request_json(f"{_VISITOR_ENDPOINT}/{area.commercial_area_id}"))
        if contents.get("areaId") != area.commercial_area_id or not isinstance(contents.get("stat"), list):
            raise MarketApiError("방문자 응답의 상권 ID 또는 stat이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)
        try:
            actual_period = AnalysisPeriod(
                start_date=datetime.strptime(contents["statStartDate"], "%Y%m%d").date(),
                end_date=datetime.strptime(contents["statEndDate"], "%Y%m%d").date(),
                timezone=period.timezone,
                day_types=period.day_types,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketApiError("방문자 응답의 통계 기간이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR) from exc

        observations: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        valid_age_groups = set(_AGE_GROUPS.values())
        for index, item in enumerate(contents["stat"]):
            try:
                if not isinstance(item, dict):
                    raise TypeError
                gender = item["gender"]
                item_age_group = item["ageGrp"]
                rate_value = item["rate"]
                if (
                    gender not in {"male", "female"}
                    or item_age_group not in valid_age_groups
                    or isinstance(rate_value, bool)
                    or not isinstance(rate_value, (int, float))
                    or not math.isfinite(rate_value)
                    or not 0 <= rate_value <= 100
                    or (gender, item_age_group) in seen
                ):
                    raise ValueError
                rate = float(rate_value)
                seen.add((gender, item_age_group))
            except (KeyError, TypeError, ValueError) as exc:
                raise MarketApiError(f"stat[{index}]의 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR) from exc
            if item_age_group != age_group:
                continue
            observations.append(
                MetricObservation(
                    metric_name="visitor_age_group_rate",
                    value=rate,
                    unit="percent",
                    period=actual_period,
                    source=_VISITOR_SOURCE,
                    is_mock=False,
                    dimensions={"gender": gender, "age_group": age_group},
                ).model_dump(mode="json")
            )
        data = {
            "area": area.model_dump(mode="json"),
            "target_age_group": age_group,
            "observations": observations,
            "missing_data": [] if observations else [f"{normalized_target_age} 방문자 비율 데이터가 없습니다."],
        }
        return ToolResult(success=True, source=_VISITOR_SOURCE, data=data, error_code=None, error_message=None, is_mock=False)
    except MarketApiError as exc:
        return _failure(_VISITOR_SOURCE, exc.error_code, str(exc))
    except Exception:
        return _failure(_VISITOR_SOURCE, ErrorCode.TOOL_INTERNAL_ERROR, "방문자 통계 처리 중 오류가 발생했습니다.")


def search_competitors(area: AreaIdentity, radius_m: int) -> ToolResult:
    """상권 좌표 주변의 '스터디카페' TMAP POI를 검색한다."""
    try:
        area = _area(area)
        if isinstance(radius_m, bool) or not isinstance(radius_m, int) or not 1 <= radius_m <= 33_000:
            raise MarketApiError("radius_m은 1~33000 범위의 정수여야 합니다.", ErrorCode.INVALID_INPUT)
        if area.latitude is None or area.longitude is None:
            raise MarketApiError("경쟁점포 검색에는 상권 좌표가 필요합니다.", ErrorCode.MISSING_REQUIRED_INPUT)
        query_radius_km = max(1, math.ceil(radius_m / 1000))
        payload = _request_json(
            _POI_ENDPOINT,
            {
                "version": 1,
                "searchKeyword": "스터디카페",
                "searchType": "all",
                "searchtypCd": "R",
                "page": 1,
                "count": 150,
                "reqCoordType": "WGS84GEO",
                "resCoordType": "WGS84GEO",
                "centerLon": area.longitude,
                "centerLat": area.latitude,
                "radius": query_radius_km,
            },
        )
        info = payload.get("searchPoiInfo")
        if not isinstance(info, dict):
            raise MarketApiError("TMAP 검색 응답 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)
        pois_node = info.get("pois")
        if not isinstance(pois_node, dict) or not isinstance(pois_node.get("poi"), list):
            raise MarketApiError("TMAP POI 목록 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)
        pois = pois_node["poi"]

        competitors_by_id: dict[str, dict[str, Any]] = {}
        for index, poi in enumerate(pois):
            try:
                if not isinstance(poi, dict):
                    raise TypeError
                poi_id = poi["id"]
                name = poi["name"]
                if not isinstance(poi_id, str) or not poi_id.strip() or not isinstance(name, str) or not name.strip():
                    raise ValueError
                latitude_value = poi.get("frontLat") or poi["noorLat"]
                longitude_value = poi.get("frontLon") or poi["noorLon"]
                if any(isinstance(value, bool) for value in (poi["radius"], latitude_value, longitude_value)):
                    raise ValueError
                distance_km = float(poi["radius"])
                latitude = float(latitude_value)
                longitude = float(longitude_value)
                if (
                    not all(math.isfinite(value) for value in (distance_km, latitude, longitude))
                    or distance_km < 0
                    or not -90 <= latitude <= 90
                    or not -180 <= longitude <= 180
                ):
                    raise ValueError
                distance_m = distance_km * 1000
                if distance_m > radius_m:
                    continue
                competitor = {
                    "poi_id": poi_id.strip(),
                    "name": name.strip(),
                    "latitude": latitude,
                    "longitude": longitude,
                    "distance_m": distance_m,
                    "category": str(poi.get("detailBizName") or poi.get("lowerBizName") or ""),
                    "address": " ".join(
                        str(poi.get(field, "")).strip()
                        for field in ("upperAddrName", "middleAddrName", "lowerAddrName", "roadName")
                        if str(poi.get(field, "")).strip()
                    ),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise MarketApiError(f"poi[{index}]의 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR) from exc
            previous = competitors_by_id.get(competitor["poi_id"])
            if previous is None or competitor["distance_m"] < previous["distance_m"]:
                competitors_by_id[competitor["poi_id"]] = competitor

        competitors = list(competitors_by_id.values())
        competitors.sort(key=lambda item: item["distance_m"])
        data = {
            "area": area.model_dump(mode="json"),
            "radius_m": radius_m,
            "retrieved_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "competitors": competitors,
        }
        return ToolResult(success=True, source=_COMPETITOR_SOURCE, data=data, error_code=None, error_message=None, is_mock=False)
    except MarketApiError as exc:
        return _failure(_COMPETITOR_SOURCE, exc.error_code, str(exc))
    except Exception:
        return _failure(_COMPETITOR_SOURCE, ErrorCode.TOOL_INTERNAL_ERROR, "경쟁점포 처리 중 오류가 발생했습니다.")


def get_rent_and_closure_data(area: AreaIdentity, period: AnalysisPeriod) -> ToolResult:
    """별도 JSON의 시연용 임대료·폐업 Mock을 반환한다."""
    source = "mock:rent_and_closure"
    try:
        area = _area(area)
        if not isinstance(period, AnalysisPeriod):
            raise MarketApiError("period 형식이 올바르지 않습니다.", ErrorCode.INVALID_INPUT)
        try:
            mock = json.loads(_RENT_MOCK_PATH.read_text(encoding="utf-8"))
            values = mock.get("areas", {}).get(area.commercial_area_id, mock["default"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise MarketApiError("임대료·폐업 Mock 파일을 읽을 수 없습니다.", ErrorCode.TOOL_INTERNAL_ERROR) from exc

        definitions = (
            ("deposit_krw", "KRW"),
            ("monthly_rent_krw", "KRW/month"),
            ("closure_rate_percent", "percent"),
        )
        observations = []
        for metric_name, unit in definitions:
            value = values.get(metric_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise MarketApiError(f"Mock의 {metric_name} 값이 올바르지 않습니다.", ErrorCode.TOOL_INTERNAL_ERROR)
            observations.append(
                MetricObservation(
                    metric_name=metric_name,
                    value=float(value),
                    unit=unit,
                    period=period,
                    source=source,
                    is_mock=True,
                    dimensions={},
                ).model_dump(mode="json")
            )

        return ToolResult(
            success=True,
            source=source,
            data={
                "area": area.model_dump(mode="json"),
                "observations": observations,
                "missing_data": [],
            },
            error_code=None,
            error_message=None,
            is_mock=True,
        )
    except MarketApiError as exc:
        return _failure(source, exc.error_code, str(exc))
    except Exception:
        return _failure(source, ErrorCode.TOOL_INTERNAL_ERROR, "임대료·폐업 Mock 처리 중 오류가 발생했습니다.")
