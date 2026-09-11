"""SK 학원 수요 API Tool."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from models.schemas import (
    AcademyDemandData,
    AnalysisPeriod,
    AreaIdentity,
    ErrorCode,
    MetricObservation,
    ToolResult,
)
from tools.api_types import SchoolAge

__all__ = ["get_academy_demand"]

_SOURCE = "SK Open API - 학령·분류별 지역 학원 순위"
_ENDPOINT = "https://apis.openapi.sk.com/puzzle/academy/ranking/districts"
_DISTRICT_CODE_PATTERN = re.compile(r"^[0-9]{10}$")
_SCHOOL_AGES = frozenset({"preschool", "elementary", "middle", "high", "univ", "all"})
_SCHOOL_AGE_LABELS: dict[SchoolAge, str] = {
    "preschool": "영유아",
    "elementary": "초등학생",
    "middle": "중학생",
    "high": "고등학생",
    "univ": "대학생",
    "all": "전체",
}


class AcademyApiError(Exception):
    def __init__(self, message: str, error_code: ErrorCode) -> None:
        super().__init__(message)
        self.error_code = error_code


def _failure(code: ErrorCode, message: str) -> ToolResult:
    return ToolResult(
        success=False,
        source=_SOURCE,
        data={},
        error_code=code,
        error_message=message,
        is_mock=False,
    )


def _api_key() -> str:
    load_dotenv()
    key = os.getenv("SK_OPEN_API_KEY")
    if not key:
        raise AcademyApiError("SK_OPEN_API_KEY가 설정되지 않았습니다.", ErrorCode.API_AUTH_ERROR)
    return key


def _school_age(school_age: str) -> SchoolAge:
    if not isinstance(school_age, str):
        raise AcademyApiError(
            "school_age는 preschool·elementary·middle·high·univ·all 중 하나여야 합니다.",
            ErrorCode.INVALID_INPUT,
        )
    normalized = school_age.strip()
    if normalized not in _SCHOOL_AGES:
        raise AcademyApiError(
            "school_age는 preschool·elementary·middle·high·univ·all 중 하나여야 합니다.",
            ErrorCode.INVALID_INPUT,
        )
    return cast(SchoolAge, normalized)


def _request(
    district_code: str,
    school_age: SchoolAge,
    *,
    timeout: float = 10.0,
    api_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    if not _DISTRICT_CODE_PATTERN.fullmatch(district_code) or timeout <= 0:
        raise AcademyApiError("법정동 코드 또는 timeout이 올바르지 않습니다.", ErrorCode.INVALID_INPUT)
    query = urlencode({"category": "all", "schoolAge": school_age})
    request = Request(
        f"{_ENDPOINT}/{district_code}?{query}",
        headers={"Accept": "application/json", "appKey": api_key or _api_key()},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise AcademyApiError("API 인증 또는 상품 권한을 확인해 주세요.", ErrorCode.API_AUTH_ERROR) from exc
        if exc.code == 429:
            raise AcademyApiError("API 호출 한도를 초과했습니다.", ErrorCode.API_RATE_LIMIT) from exc
        if exc.code == 400:
            raise AcademyApiError("API 요청 파라미터가 올바르지 않습니다.", ErrorCode.API_BAD_REQUEST) from exc
        raise AcademyApiError("SK 학원 API 호출에 실패했습니다.", ErrorCode.API_RESPONSE_ERROR) from exc
    except (TimeoutError, URLError) as exc:
        if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
            raise AcademyApiError("API 요청 시간이 초과되었습니다.", ErrorCode.API_TIMEOUT) from exc
        raise AcademyApiError("SK 학원 API에 연결할 수 없습니다.", ErrorCode.API_RESPONSE_ERROR) from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcademyApiError("API 응답이 올바른 JSON이 아닙니다.", ErrorCode.API_RESPONSE_ERROR) from exc
    if not isinstance(payload, dict):
        raise AcademyApiError("API 응답 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR)
    return payload


def _parse(
    payload: dict[str, Any],
    area: AreaIdentity,
    requested_period: AnalysisPeriod,
    expected_school_age: SchoolAge,
) -> AcademyDemandData:
    status = payload.get("status")
    if not isinstance(status, dict) or status.get("code") != "00":
        code = ErrorCode.NO_DATA if isinstance(status, dict) and status.get("code") == "NO_DATA" else ErrorCode.API_RESPONSE_ERROR
        raise AcademyApiError("SK 학원 API가 실패 상태를 반환했습니다.", code)

    contents = payload.get("contents")
    if not isinstance(contents, dict) or contents.get("districtCode") != area.administrative_code:
        raise AcademyApiError("응답의 법정동 코드가 요청과 다릅니다.", ErrorCode.API_RESPONSE_ERROR)
    expected_label = _SCHOOL_AGE_LABELS[expected_school_age]
    if contents.get("category") != "전체" or contents.get("schoolAge") != expected_label:
        raise AcademyApiError("응답의 분류 또는 학령이 요청과 다릅니다.", ErrorCode.API_RESPONSE_ERROR)
    stat = contents.get("stat")
    if not isinstance(stat, list):
        raise AcademyApiError("응답의 stat 값이 배열이 아닙니다.", ErrorCode.API_RESPONSE_ERROR)

    try:
        start_date = datetime.strptime(contents["statStartDate"], "%Y%m%d").date()
        end_date = datetime.strptime(contents["statEndDate"], "%Y%m%d").date()
        actual_period = AnalysisPeriod(
            start_date=start_date,
            end_date=end_date,
            timezone=requested_period.timezone,
            day_types=requested_period.day_types,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AcademyApiError("응답의 통계 기간이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR) from exc

    observations: list[MetricObservation] = []
    academy_ids: set[str] = set()
    for index, item in enumerate(stat):
        try:
            if not isinstance(item, dict):
                raise TypeError
            count = item["count"]
            if (
                isinstance(count, bool)
                or not isinstance(count, (int, float))
                or not math.isfinite(count)
                or count < 0
            ):
                raise ValueError
            for field in ("ypId", "ypName", "category", "schoolAge"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError
            if item["schoolAge"] != expected_label:
                raise ValueError
            dimensions = {
                "academy_id": item["ypId"].strip(),
                "academy_name": item["ypName"].strip(),
                "category": item["category"].strip(),
                "school_age": item["schoolAge"].strip(),
            }
            if dimensions["academy_id"] in academy_ids:
                raise ValueError
            academy_ids.add(dimensions["academy_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AcademyApiError(
                f"stat[{index}]의 필드 형식이 올바르지 않습니다.", ErrorCode.API_RESPONSE_ERROR
            ) from exc

        observation = MetricObservation(
            metric_name="estimated_academy_call_customers",
            value=float(count),
            unit="persons",
            period=actual_period,
            source=_SOURCE,
            is_mock=False,
            dimensions=dimensions,
        )
        observations.append(observation)

    missing = [] if observations else ["학원 순위 데이터가 없습니다. 학원이 0개라는 의미는 아닙니다."]
    return AcademyDemandData(
        commercial_area_id=area.commercial_area_id,
        administrative_code=area.administrative_code,
        observations=observations,
        missing_data=missing,
    )


def get_academy_demand(
    area: AreaIdentity,
    period: AnalysisPeriod,
    school_age: SchoolAge = "all",
) -> ToolResult:
    """법정동의 학령별 상위 학원 추정 통화 고객수를 조회한다.

    사용자 타깃 연령대는 학령으로 추정 변환하지 않는다. 특정 학령 요청이 없으면
    API의 전체 학령 코드인 ``all``을 사용한다.
    """
    try:
        if not isinstance(area, AreaIdentity) or not isinstance(period, AnalysisPeriod):
            raise AcademyApiError("area와 period의 형식이 올바르지 않습니다.", ErrorCode.INVALID_INPUT)
        if not area.administrative_code:
            raise AcademyApiError("학원 조회에는 법정동 코드가 필요합니다.", ErrorCode.MISSING_REQUIRED_INPUT)
        if not _DISTRICT_CODE_PATTERN.fullmatch(area.administrative_code):
            raise AcademyApiError("법정동 코드는 10자리 숫자여야 합니다.", ErrorCode.INVALID_INPUT)

        normalized_school_age = _school_age(school_age)
        payload = _request(area.administrative_code, normalized_school_age)
        data = _parse(payload, area, period, normalized_school_age)
        return ToolResult(
            success=True,
            source=_SOURCE,
            data=data.model_dump(mode="json"),
            error_code=None,
            error_message=None,
            is_mock=False,
        )
    except AcademyApiError as exc:
        return _failure(exc.error_code, str(exc))
    except Exception:
        return _failure(ErrorCode.TOOL_INTERNAL_ERROR, "학원 수요 처리 중 오류가 발생했습니다.")
