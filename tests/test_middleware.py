from dataclasses import dataclass

import pytest
from langchain.messages import ToolMessage
from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime

from memory.state import create_initial_state, merge_business_conditions
from middleware.middleware import (
    MaxIterationReached,
    SensitiveActionExecutionDenied,
    can_continue_agent_iteration,
    ensure_agent_iteration_available,
    ensure_sensitive_action_approved,
    execute_with_retry,
    sensitive_action_execution_guard,
)
from models.schemas import BusinessConditions, ErrorCode, PendingAction, RuntimeContext, ToolResult


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


def test_hitl_action_tools_allow_only_approve_or_reject():
    from middleware.middleware import build_human_in_the_loop_middleware

    middleware = build_human_in_the_loop_middleware()
    for tool_name in ("send_analysis_report", "create_site_visit_event"):
        allowed_decisions = middleware.interrupt_on[tool_name]["allowed_decisions"]
        assert allowed_decisions == ["approve", "reject"]
        assert "edit" not in allowed_decisions


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
    action = pending_action().transition_to("approved")

    with pytest.raises(SensitiveActionExecutionDenied):
        ensure_sensitive_action_approved("create_site_visit_event", action, runtime_context())


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
