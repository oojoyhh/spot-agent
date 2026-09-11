from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest
from langchain.messages import ToolMessage
from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime

from memory.state import create_initial_state, merge_business_conditions
from middleware.middleware import (
    MaxIterationReached,
    SensitiveActionExecutionDenied,
    can_continue_agent_iteration,
    create_tool_retry_middleware,
    ensure_agent_iteration_available,
    ensure_sensitive_action_approved,
    execute_with_retry,
    sensitive_action_execution_guard,
)
from models.schemas import ActionResult, BusinessConditions, ErrorCode, PendingAction, RuntimeContext, ToolResult
from tools.action_tools import send_analysis_report
from tools import mock_tools
from tools.mock_tools import mock_tool_call_provider


@dataclass
class FakeToolResult:
    success: bool
    error_code: str | None = None
    source: str = "test"


def failure(code: str) -> FakeToolResult:
    return FakeToolResult(False, code)


def tool_failure(error_code: ErrorCode) -> ToolResult:
    return ToolResult(
        success=False,
        source="test:api",
        data={},
        error_code=error_code,
        is_mock=False,
    )


def pending_action(**overrides) -> PendingAction:
    values = {
        "action_id": "action-1",
        "action_type": "send_report",
        "payload_version": 1,
        "display_summary": "분석 보고서 전송",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    values.update(overrides)
    return PendingAction(**values)


def runtime_context(**overrides) -> RuntimeContext:
    values = {"user_id": "user-1", "session_id": "session-1", "user_role": "user"}
    values.update(overrides)
    return RuntimeContext(**values)


def mock_request(tool_name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(tool_call={"name": tool_name, "args": args, "id": "mock-call"})


def mock_area() -> dict:
    return {
        "commercial_area_id": "9307",
        "administrative_code": "1168010100",
        "area_name": "역삼역남부 3번출구",
        "latitude": 37.50012959,
        "longitude": 127.03529551,
    }


def mock_period() -> dict:
    return {
        "start_date": date(2026, 9, 10),
        "end_date": date(2026, 9, 10),
        "day_types": ["weekday"],
        "start_time": "18:00",
        "end_time": "20:00",
    }


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


def test_tool_result_timeout_retries_exactly_three_times():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return tool_failure(ErrorCode.API_TIMEOUT)

    result = execute_with_retry(operation)
    assert result.error_code is ErrorCode.API_TIMEOUT
    assert calls == 3


@pytest.mark.parametrize(
    "error_code",
    [ErrorCode.API_TIMEOUT, ErrorCode.API_RATE_LIMIT, ErrorCode.API_RESPONSE_ERROR],
)
def test_retryable_tool_result_error_codes_retry_exactly_three_times(error_code):
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return tool_failure(error_code)

    assert execute_with_retry(operation).error_code is error_code
    assert calls == 3


def test_tool_result_auth_error_does_not_retry():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return tool_failure(ErrorCode.API_AUTH_ERROR)

    assert execute_with_retry(operation).error_code is ErrorCode.API_AUTH_ERROR
    assert calls == 1


@pytest.mark.parametrize(
    "error_code",
    [
        ErrorCode.API_AUTH_ERROR,
        ErrorCode.API_BAD_REQUEST,
        ErrorCode.INVALID_INPUT,
        ErrorCode.AREA_NOT_FOUND,
        ErrorCode.NO_DATA,
        ErrorCode.STATION_NOT_FOUND,
        ErrorCode.MISSING_REQUIRED_INPUT,
        ErrorCode.TOOL_INTERNAL_ERROR,
    ],
)
def test_non_retryable_tool_result_error_codes_run_once(error_code):
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return tool_failure(error_code)

    assert execute_with_retry(operation).error_code is error_code
    assert calls == 1


@pytest.mark.parametrize(
    "error_code",
    [ErrorCode.NO_DATA, ErrorCode.UNSUPPORTED_AREA, ErrorCode.AREA_NOT_FOUND],
)
def test_tool_result_no_data_or_area_errors_do_not_retry_or_fallback(error_code):
    calls = mock_calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return tool_failure(error_code)

    def mock():
        nonlocal mock_calls
        mock_calls += 1
        return ToolResult(success=True, source="mock:test", data={}, is_mock=True)

    assert execute_with_retry(operation, mock_provider=mock).error_code is error_code
    assert (calls, mock_calls) == (1, 0)


@pytest.mark.parametrize(
    "error_code",
    [
        ErrorCode.NO_DATA,
        ErrorCode.AREA_NOT_FOUND,
        ErrorCode.STATION_NOT_FOUND,
        ErrorCode.MISSING_REQUIRED_INPUT,
        ErrorCode.INVALID_INPUT,
    ],
)
def test_non_retryable_tool_results_skip_cache_and_mock_fallback(error_code):
    calls = cache_calls = mock_calls = 0
    original = tool_failure(error_code)

    def operation():
        nonlocal calls
        calls += 1
        return original

    def cache():
        nonlocal cache_calls
        cache_calls += 1
        return ToolResult(success=True, source="cache:test", data={}, is_mock=False)

    def mock():
        nonlocal mock_calls
        mock_calls += 1
        return ToolResult(success=True, source="mock:test", data={}, is_mock=True)

    assert execute_with_retry(operation, cache_provider=cache, mock_provider=mock) is original
    assert (calls, cache_calls, mock_calls) == (1, 0, 0)


@pytest.mark.parametrize("cache_hit", [True, False], ids=["cache_hit", "cache_miss"])
def test_retryable_tool_result_uses_cache_then_mock_after_retry_exhaustion(cache_hit):
    calls = cache_calls = mock_calls = 0
    cached = ToolResult(success=True, source="cache:test", data={}, is_mock=False)
    mocked = ToolResult(success=True, source="mock:test", data={}, is_mock=True)

    def operation():
        nonlocal calls
        calls += 1
        return tool_failure(ErrorCode.API_TIMEOUT)

    def cache():
        nonlocal cache_calls
        cache_calls += 1
        return cached if cache_hit else None

    def mock():
        nonlocal mock_calls
        mock_calls += 1
        return mocked

    result = execute_with_retry(operation, cache_provider=cache, mock_provider=mock)
    assert result is (cached if cache_hit else mocked)
    assert (calls, cache_calls, mock_calls) == (3, 1, 0 if cache_hit else 1)


def test_tool_result_success_returns_immediately():
    calls = 0
    success = ToolResult(success=True, source="test:api", data={"area": "강남역"}, is_mock=False)

    def operation():
        nonlocal calls
        calls += 1
        return success

    assert execute_with_retry(operation) is success
    assert calls == 1


def test_tool_result_mock_fallback_preserves_provider_contract():
    calls = cache_calls = mock_calls = 0
    mock_result = ToolResult(
        success=True,
        source="mock:api",
        data={"area": "강남역"},
        error_code=ErrorCode.API_TIMEOUT,
        error_message="API timeout; mock fallback used",
        is_mock=True,
    )

    def operation():
        nonlocal calls
        calls += 1
        return tool_failure(ErrorCode.API_TIMEOUT)

    def cache():
        nonlocal cache_calls
        cache_calls += 1
        return None

    def mock():
        nonlocal mock_calls
        mock_calls += 1
        return mock_result

    result = execute_with_retry(operation, cache_provider=cache, mock_provider=mock)
    assert result is mock_result
    assert result.success and result.is_mock
    assert isinstance(result.data, dict)
    assert result.error_code is ErrorCode.API_TIMEOUT
    assert result.error_message is not None
    assert (calls, cache_calls, mock_calls) == (3, 1, 1)


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("get_academy_demand", {"area": mock_area(), "period": mock_period(), "school_age": "high"}),
        ("get_station_exit_traffic", {"station_id": "221", "period": mock_period()}),
        ("get_visitor_demographics", {"area": mock_area(), "period": mock_period(), "target_age": "20대"}),
        ("get_district_congestion", {"area": mock_area(), "period": mock_period()}),
        ("search_competitors", {"area": mock_area(), "radius_m": 500}),
    ],
)
def test_mock_provider_resolves_each_agreed_agent_tool_name(tool_name, args):
    message = mock_tool_call_provider(mock_request(tool_name, args))

    assert message is not None
    result = ToolResult.model_validate_json(message.content)
    assert message.name == tool_name and message.tool_call_id == "mock-call"
    assert result.success and result.is_mock and result.source == f"mock:{tool_name}"


def test_unsupported_mock_tool_name_keeps_original_retryable_failure():
    calls = mock_calls = 0
    request = mock_request("typo_get_competitors", {})
    original = ToolResult(
        success=False, source="api", data={}, error_code=ErrorCode.API_TIMEOUT,
        error_message="upstream timeout", is_mock=False,
    )

    def handler(_request):
        nonlocal calls
        calls += 1
        return ToolMessage(content=original.model_dump_json(), tool_call_id="mock-call")

    def provider(provider_request):
        nonlocal mock_calls
        mock_calls += 1
        return mock_tool_call_provider(provider_request)

    result = create_tool_retry_middleware(mock_provider=provider).wrap_tool_call(request, handler)
    assert ToolResult.model_validate_json(result.content) == original
    assert (calls, mock_calls) == (3, 1)


def test_mock_generation_failure_keeps_original_retryable_failure(monkeypatch):
    calls = 0
    request = mock_request(
        "get_academy_demand",
        {"area": mock_area(), "period": mock_period(), "school_age": "high"},
    )
    original = ToolResult(success=False, source="api", data={}, error_code=ErrorCode.API_TIMEOUT, is_mock=False)

    def unavailable_mock_data():
        raise OSError("fixture unavailable")

    def handler(_request):
        nonlocal calls
        calls += 1
        return ToolMessage(content=original.model_dump_json(), tool_call_id="mock-call")

    monkeypatch.setattr(mock_tools, "_load_mock", unavailable_mock_data)
    result = create_tool_retry_middleware(mock_provider=mock_tool_call_provider).wrap_tool_call(request, handler)
    assert ToolResult.model_validate_json(result.content) == original
    assert calls == 3


@pytest.mark.parametrize(
    "error_code",
    [ErrorCode.API_TIMEOUT, ErrorCode.API_RATE_LIMIT, ErrorCode.API_RESPONSE_ERROR],
)
def test_retryable_errors_use_actual_mock_provider_after_three_attempts(error_code):
    calls = mock_calls = 0
    request = mock_request(
        "get_academy_demand",
        {"area": mock_area(), "period": mock_period(), "school_age": "high"},
    )
    original = ToolResult(
        success=False, source="academy-api", data={}, error_code=error_code,
        error_message=f"upstream {error_code.value}", is_mock=False,
    )

    def handler(_request):
        nonlocal calls
        calls += 1
        return ToolMessage(content=original.model_dump_json(), tool_call_id="mock-call")

    def provider(provider_request):
        nonlocal mock_calls
        mock_calls += 1
        return mock_tool_call_provider(provider_request)

    message = create_tool_retry_middleware(mock_provider=provider).wrap_tool_call(request, handler)
    result = ToolResult.model_validate_json(message.content)
    assert (calls, mock_calls) == (3, 1)
    assert result.success and result.is_mock and result.source == "mock:get_academy_demand"
    assert result.error_code is error_code
    assert result.error_message == f"upstream {error_code.value}"


@pytest.mark.parametrize(
    "error_code",
    [ErrorCode.AREA_NOT_FOUND, ErrorCode.STATION_NOT_FOUND, ErrorCode.NO_DATA, ErrorCode.INVALID_INPUT],
)
def test_non_retryable_errors_do_not_call_actual_mock_provider(error_code):
    calls = mock_calls = 0
    request = mock_request(
        "get_academy_demand",
        {"area": mock_area(), "period": mock_period(), "school_age": "high"},
    )
    original = ToolResult(success=False, source="api", data={}, error_code=error_code, is_mock=False)

    def handler(_request):
        nonlocal calls
        calls += 1
        return ToolMessage(content=original.model_dump_json(), tool_call_id="mock-call")

    def provider(provider_request):
        nonlocal mock_calls
        mock_calls += 1
        return mock_tool_call_provider(provider_request)

    message = create_tool_retry_middleware(mock_provider=provider).wrap_tool_call(request, handler)
    assert ToolResult.model_validate_json(message.content) == original
    assert (calls, mock_calls) == (1, 0)


def test_successful_zero_competitor_result_skips_mock_provider():
    calls = mock_calls = 0
    request = mock_request("search_competitors", {"area": mock_area(), "radius_m": 500})
    original = ToolResult(success=True, source="market-api", data={"competitors": []}, is_mock=False)

    def handler(_request):
        nonlocal calls
        calls += 1
        return ToolMessage(content=original.model_dump_json(), tool_call_id="mock-call")

    def provider(provider_request):
        nonlocal mock_calls
        mock_calls += 1
        return mock_tool_call_provider(provider_request)

    message = create_tool_retry_middleware(mock_provider=provider).wrap_tool_call(request, handler)
    assert ToolResult.model_validate_json(message.content) == original
    assert (calls, mock_calls) == (1, 0)


def test_hitl_action_tools_allow_only_approve_or_reject():
    from middleware.middleware import build_human_in_the_loop_middleware

    middleware = build_human_in_the_loop_middleware()
    allowed_decisions = middleware.interrupt_on["send_analysis_report"]["allowed_decisions"]
    assert allowed_decisions == ["approve", "reject"]
    assert "edit" not in allowed_decisions
    assert "create_site_visit_event" not in middleware.interrupt_on


def test_sensitive_action_execution_allows_matching_approved_action():
    action = pending_action().transition_to("approved")
    assert ensure_sensitive_action_approved("send_analysis_report", action, runtime_context()) is None


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_sensitive_action_execution_blocks_non_approved_action(status):
    action = pending_action()
    if status == "rejected":
        action = action.transition_to("rejected")

    with pytest.raises(SensitiveActionExecutionDenied):
        ensure_sensitive_action_approved("send_analysis_report", action, runtime_context())


def test_sensitive_action_execution_blocks_action_type_mismatch():
    action = pending_action(action_type="create_site_visit").transition_to("approved")

    with pytest.raises(SensitiveActionExecutionDenied):
        ensure_sensitive_action_approved("send_analysis_report", action, runtime_context())


def test_sensitive_action_execution_blocks_user_mismatch():
    action = pending_action().transition_to("approved")

    with pytest.raises(SensitiveActionExecutionDenied):
        ensure_sensitive_action_approved("send_analysis_report", action, runtime_context(user_id="other-user"))


def test_sensitive_action_execution_blocks_session_mismatch():
    action = pending_action().transition_to("approved")

    with pytest.raises(SensitiveActionExecutionDenied):
        ensure_sensitive_action_approved("send_analysis_report", action, runtime_context(session_id="other-session"))


def test_sensitive_action_execution_blocks_missing_pending_action():
    with pytest.raises(SensitiveActionExecutionDenied):
        ensure_sensitive_action_approved("send_analysis_report", None, runtime_context())


def test_sensitive_action_adapter_checks_state_and_context_before_handler():
    calls = 0
    state = {"pending_action": pending_action().transition_to("approved")}
    request = ToolCallRequest(
        tool_call={"name": "send_analysis_report", "args": {}, "id": "call-1", "type": "tool_call"},
        tool=None,
        state=state,
        runtime=ToolRuntime(
            state=state,
            context=runtime_context(),
            config={},
            stream_writer=lambda _: None,
            tool_call_id="call-1",
            store=None,
        ),
    )

    def handler(_request):
        nonlocal calls
        calls += 1
        return "executed"

    assert sensitive_action_execution_guard.wrap_tool_call(request, handler) == "executed"
    assert calls == 1

    state["pending_action"] = pending_action()
    with pytest.raises(SensitiveActionExecutionDenied):
        sensitive_action_execution_guard.wrap_tool_call(request, handler)
    assert calls == 1


@pytest.mark.parametrize("current_iteration", [0, 4])
def test_max_iteration_policy_allows_calls_below_limit(current_iteration):
    assert can_continue_agent_iteration(current_iteration, max_iterations=5)


@pytest.mark.parametrize("current_iteration", [5, 6])
def test_max_iteration_policy_blocks_calls_at_or_above_limit(current_iteration):
    assert not can_continue_agent_iteration(current_iteration, max_iterations=5)
    with pytest.raises(MaxIterationReached) as exc_info:
        ensure_agent_iteration_available(current_iteration, max_iterations=5)
    assert exc_info.value.error_code is ErrorCode.MAX_ITERATION_REACHED


@pytest.mark.parametrize(
    ("current_iteration", "max_iterations"),
    [(-1, 5), (0, 0), (0, -1)],
)
def test_max_iteration_policy_rejects_invalid_counts(current_iteration, max_iterations):
    with pytest.raises(ValueError):
        can_continue_agent_iteration(current_iteration, max_iterations)


# Memory가 조건 변경으로 승인 대기를 무효화하면, middleware가 stale action의 실제 실행을 막아야 한다.
@pytest.mark.parametrize(
    ("condition_update", "expected_update_key", "preserves_analysis"),
    [
        (BusinessConditions(monthly_rent_budget=3_000_000), "tool_results", False),
        (BusinessConditions(preferred_region="마포구"), "searched_areas", False),
        (BusinessConditions(priority_metrics=["rent_score"]), "pending_action", True),
    ],
    ids=["monthly_rent", "preferred_region", "priority_metrics"],
)
def test_condition_change_invalidates_approved_action_before_sensitive_tool_execution(
    condition_update,
    expected_update_key,
    preserves_analysis,
):
    state = create_initial_state(
        BusinessConditions(
            preferred_region="강남구",
            deposit_budget=50_000_000,
            monthly_rent_budget=2_500_000,
            target_age="20대",
            operating_start_time="09:00",
            operating_end_time="23:00",
            priority_metrics=["academy_demand_score"],
        )
    )
    state["pending_action"] = pending_action().transition_to("approved")
    calls = 0
    request = ToolCallRequest(
        tool_call={"name": "send_analysis_report", "args": {}, "id": "call-1", "type": "tool_call"},
        tool=None,
        state=state,
        runtime=ToolRuntime(
            state=state,
            context=runtime_context(),
            config={},
            stream_writer=lambda _: None,
            tool_call_id="call-1",
            store=None,
        ),
    )

    def handler(_request):
        nonlocal calls
        calls += 1
        return "executed"

    assert sensitive_action_execution_guard.wrap_tool_call(request, handler) == "executed"
    assert calls == 1

    state_update = merge_business_conditions(state, condition_update)
    assert state_update["pending_action"] is None
    assert expected_update_key in state_update
    if preserves_analysis:
        assert "tool_results" not in state_update

    state.update(state_update)
    with pytest.raises(SensitiveActionExecutionDenied):
        sensitive_action_execution_guard.wrap_tool_call(request, handler)
    assert calls == 1


def test_sensitive_action_guard_executes_actual_mock_report_tool_for_approved_action():
    action = pending_action().transition_to("approved")
    state = {"pending_action": action}
    calls = 0
    request = ToolCallRequest(
        tool_call={"name": "send_analysis_report", "args": {}, "id": "call-action", "type": "tool_call"},
        tool=None,
        state=state,
        runtime=ToolRuntime(
            state=state,
            context=runtime_context(),
            config={},
            stream_writer=lambda _: None,
            tool_call_id="call-action",
            store=None,
        ),
    )

    def handler(guarded_request):
        nonlocal calls
        calls += 1
        return send_analysis_report(guarded_request.state["pending_action"])

    result = sensitive_action_execution_guard.wrap_tool_call(request, handler)
    action_result = ActionResult.model_validate(result.data)
    assert calls == 1
    assert result.success and result.is_mock
    assert action_result.status == "simulated"
    assert action_result.is_mock
    assert "실제 보고서는 전송되지 않았습니다" in action_result.message


@pytest.mark.parametrize(
    ("action", "context"),
    [
        (pending_action(), runtime_context()),
        (pending_action().transition_to("rejected"), runtime_context()),
        (pending_action().transition_to("approved"), runtime_context(user_id="other-user")),
        (pending_action().transition_to("approved"), runtime_context(session_id="other-session")),
    ],
    ids=["pending", "rejected", "user_mismatch", "session_mismatch"],
)
def test_sensitive_action_guard_blocks_actual_report_tool_without_approved_matching_action(action, context):
    state = {"pending_action": action}
    calls = 0
    request = ToolCallRequest(
        tool_call={"name": "send_analysis_report", "args": {}, "id": "call-blocked", "type": "tool_call"},
        tool=None,
        state=state,
        runtime=ToolRuntime(
            state=state,
            context=context,
            config={},
            stream_writer=lambda _: None,
            tool_call_id="call-blocked",
            store=None,
        ),
    )

    def handler(guarded_request):
        nonlocal calls
        calls += 1
        return send_analysis_report(guarded_request.state["pending_action"])

    with pytest.raises(SensitiveActionExecutionDenied):
        sensitive_action_execution_guard.wrap_tool_call(request, handler)
    assert calls == 0
