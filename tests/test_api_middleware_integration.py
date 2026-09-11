"""역할 1 API Tool과 역할 3 Middleware의 연결 계약 테스트."""

from collections.abc import Callable
from datetime import date

import pytest

from middleware.middleware import execute_with_retry
from models.schemas import AnalysisPeriod, AreaIdentity, ErrorCode, ToolResult
from tools import academy_tools, market_tools, subway_tools


def _area() -> AreaIdentity:
    return AreaIdentity(
        commercial_area_id="9307",
        administrative_code="1168010100",
        area_name="역삼역남부 3번출구",
        latitude=37.500692,
        longitude=127.036978,
    )


def _period() -> AnalysisPeriod:
    return AnalysisPeriod(
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 10),
        day_types=["weekday"],
        start_time="18:00",
        end_time="20:00",
    )


def _academy_call() -> ToolResult:
    return academy_tools.get_academy_demand(_area(), _period())


def _subway_call() -> ToolResult:
    return subway_tools.get_station_exit_traffic("221", _period())


def _market_call() -> ToolResult:
    return market_tools.get_district_congestion(_area(), _period())


@pytest.mark.parametrize(
    ("module", "dependency_name", "error_factory", "operation"),
    [
        (
            academy_tools,
            "_request",
            lambda: academy_tools.AcademyApiError("timeout", ErrorCode.API_TIMEOUT),
            _academy_call,
        ),
        (
            subway_tools,
            "_fetch_station_exit_traffic",
            lambda: subway_tools.SubwayTimeoutError("timeout", ErrorCode.API_TIMEOUT),
            _subway_call,
        ),
        (
            market_tools,
            "_request_json",
            lambda: market_tools.MarketApiError("timeout", ErrorCode.API_TIMEOUT),
            _market_call,
        ),
    ],
    ids=["academy", "subway", "market"],
)
def test_middleware_owns_retry_for_api_tools(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    dependency_name: str,
    error_factory: Callable[[], Exception],
    operation: Callable[[], ToolResult],
) -> None:
    """Tool 내부 호출은 1회씩이며 Middleware 적용 시 총 3회로 제한된다."""
    calls = 0

    def fail(*args: object, **kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        raise error_factory()

    monkeypatch.setattr(module, dependency_name, fail)

    result = execute_with_retry(operation)

    assert result.success is False
    assert result.error_code is ErrorCode.API_TIMEOUT
    assert calls == 3


@pytest.mark.parametrize(
    ("module", "dependency_name", "error_factory", "operation"),
    [
        (
            academy_tools,
            "_request",
            lambda: academy_tools.AcademyApiError("auth", ErrorCode.API_AUTH_ERROR),
            _academy_call,
        ),
        (
            subway_tools,
            "_fetch_station_exit_traffic",
            lambda: subway_tools.SubwayAuthError("auth", ErrorCode.API_AUTH_ERROR),
            _subway_call,
        ),
        (
            market_tools,
            "_request_json",
            lambda: market_tools.MarketApiError("auth", ErrorCode.API_AUTH_ERROR),
            _market_call,
        ),
    ],
    ids=["academy", "subway", "market"],
)
def test_middleware_does_not_retry_permanent_api_errors(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    dependency_name: str,
    error_factory: Callable[[], Exception],
    operation: Callable[[], ToolResult],
) -> None:
    """인증 오류는 ToolResult로 변환된 뒤에도 재시도하지 않는다."""
    calls = 0

    def fail(*args: object, **kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        raise error_factory()

    monkeypatch.setattr(module, dependency_name, fail)

    result = execute_with_retry(operation)

    assert result.success is False
    assert result.error_code is ErrorCode.API_AUTH_ERROR
    assert calls == 1


def test_middleware_does_not_retry_successful_local_api_tool() -> None:
    """외부 요청이 없는 근처 역 조회 성공은 한 번에 반환한다."""
    calls = 0
    original = subway_tools.find_nearby_stations

    def operation() -> ToolResult:
        nonlocal calls
        calls += 1
        return original(37.500622, 127.036456, 100)

    result = execute_with_retry(operation)

    assert result.success is True
    assert result.is_mock is False
    assert calls == 1
