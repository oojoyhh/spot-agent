from dataclasses import dataclass

import pytest
from langchain.messages import ToolMessage

from middleware.middleware import execute_with_retry


@dataclass
class FakeToolResult:
    success: bool
    error_code: str | None = None
    source: str = "test"


def failure(code: str) -> FakeToolResult:
    return FakeToolResult(False, code)


def test_mw_01_timeout_retries_exactly_three_times():
    calls = 0
    def operation():
        nonlocal calls
        calls += 1
        return failure("API_TIMEOUT")
    assert execute_with_retry(operation).error_code == "API_TIMEOUT"
    assert calls == 3


def test_mw_02_auth_error_does_not_retry():
    calls = 0
    def operation():
        nonlocal calls
        calls += 1
        return failure("API_AUTH_ERROR")
    assert execute_with_retry(operation).error_code == "API_AUTH_ERROR"
    assert calls == 1


def test_tool_wrapper_retries_serialized_tool_result():
    from middleware.middleware import tool_retry_middleware

    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return ToolMessage(content='{"success": false, "error_code": "API_TIMEOUT"}', tool_call_id="call-1")

    result = tool_retry_middleware.wrap_tool_call(None, handler)
    assert result.content == '{"success": false, "error_code": "API_TIMEOUT"}'
    assert calls == 3


def test_mw_03_cache_hit_wins_after_retries():
    calls = cache_calls = mock_calls = 0
    cached = FakeToolResult(True, source="cache")
    def operation():
        nonlocal calls
        calls += 1
        return failure("API_TIMEOUT")
    def cache():
        nonlocal cache_calls
        cache_calls += 1
        return cached
    def mock():
        nonlocal mock_calls
        mock_calls += 1
        return FakeToolResult(True, source="mock")
    assert execute_with_retry(operation, cache_provider=cache, mock_provider=mock) is cached
    assert (calls, cache_calls, mock_calls) == (3, 1, 0)


def test_mw_04_mock_used_after_cache_miss():
    calls = cache_calls = mock_calls = 0
    def operation():
        nonlocal calls
        calls += 1
        return failure("API_RESPONSE_ERROR")
    def cache():
        nonlocal cache_calls
        cache_calls += 1
        return None
    def mock():
        nonlocal mock_calls
        mock_calls += 1
        return FakeToolResult(True, source="mock")
    result = execute_with_retry(operation, cache_provider=cache, mock_provider=mock)
    assert result.source == "mock"
    assert (calls, cache_calls, mock_calls) == (3, 1, 1)


def test_mw_05_returns_original_failure_without_fallback():
    original = failure("API_RATE_LIMIT")
    assert execute_with_retry(lambda: original) is original


@pytest.mark.parametrize("error_code", ["NO_DATA", "UNSUPPORTED_AREA", "AREA_NOT_FOUND"])
def test_mw_06_no_data_and_area_errors_do_not_retry_or_fallback(error_code):
    calls = mock_calls = 0
    def operation():
        nonlocal calls
        calls += 1
        return failure(error_code)
    def mock():
        nonlocal mock_calls
        mock_calls += 1
        return FakeToolResult(True, source="mock")
    assert execute_with_retry(operation, mock_provider=mock).error_code == error_code
    assert (calls, mock_calls) == (1, 0)
