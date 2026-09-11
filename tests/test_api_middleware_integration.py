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


@pytest.mark.parametrize(
    ("operation", "error_code"),
    [
        (lambda: subway_tools.find_nearby_stations(0.0, 0.0, 500), ErrorCode.STATION_NOT_FOUND),
        (
            lambda: academy_tools.get_academy_demand(
                AreaIdentity(
                    commercial_area_id="9307",
                    administrative_code=None,
                    area_name="역삼역남부 3번출구",
                    latitude=37.500692,
                    longitude=127.036978,
                ),
                _period(),
            ),
            ErrorCode.MISSING_REQUIRED_INPUT,
        ),
    ],
    ids=["subway_station_not_found", "academy_missing_required_input"],
)
def test_actual_local_tool_non_retryable_results_skip_retry_and_fallback(
    operation: Callable[[], ToolResult],
    error_code: ErrorCode,
) -> None:
    """실제 Tool의 영구 오류는 Middleware를 거쳐도 재시도·대체 결과로 바뀌지 않는다."""
    calls = cache_calls = mock_calls = 0

    def counted_operation() -> ToolResult:
        nonlocal calls
        calls += 1
        return operation()

    def cache() -> ToolResult:
        nonlocal cache_calls
        cache_calls += 1
        return ToolResult(success=True, source="cache:test", data={}, is_mock=False)

    def mock() -> ToolResult:
        nonlocal mock_calls
        mock_calls += 1
        return ToolResult(success=True, source="mock:test", data={}, is_mock=True)

    result = execute_with_retry(counted_operation, cache_provider=cache, mock_provider=mock)
    assert result.success is False
    assert result.error_code is error_code
    assert (calls, cache_calls, mock_calls) == (1, 0, 0)


def test_actual_market_area_not_found_skips_retry_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """외부 요청 없이 실제 market Tool의 AREA_NOT_FOUND 결과를 Middleware에 연결한다."""
    monkeypatch.setattr(market_tools, "_fetch_areas", lambda: [{"areaId": "9195", "areaName": "명동"}])
    calls = cache_calls = mock_calls = 0

    def operation() -> ToolResult:
        nonlocal calls
        calls += 1
        return market_tools.search_supported_districts("없는상권")

    def cache() -> ToolResult:
        nonlocal cache_calls
        cache_calls += 1
        return ToolResult(success=True, source="cache:test", data=[], is_mock=False)

    def mock() -> ToolResult:
        nonlocal mock_calls
        mock_calls += 1
        return ToolResult(success=True, source="mock:test", data=[], is_mock=True)

    result = execute_with_retry(operation, cache_provider=cache, mock_provider=mock)
    assert result.error_code is ErrorCode.AREA_NOT_FOUND
    assert (calls, cache_calls, mock_calls) == (1, 0, 0)
