"""Agent Graph의 외부 Tool 복구·승인 경계.

실행 흐름: 외부 Tool 호출 → retry 가능 여부 판정 → 최초 1회 + retry 최대
2회 → 실패 지속 시 cache → cache miss면 mock → 대체 수단도 없으면 원 실패
반환이다.

``should_retry``는 일시 장애와 영구/의미 없는 실패를 구분한다.
``execute_with_retry``는 framework-independent retry/fallback core이고,
``create_tool_retry_middleware`` 및 ``tool_retry_middleware``는 이를
LangChain ``wrap_tool_call``에 연결한다. ``build_human_in_the_loop_middleware``는
외부 부작용 Tool이 사용자 승인 전에 실행되지 않도록 구성한다.

HumanInTheLoopMiddleware가 사용자 승인/거절 흐름을 담당한다면, sensitive
action execution guard는 모델 validation과 HITL 이후에도 실제 외부 행동
직전에 승인 상태와 실행 주체를 재확인하는 최종 방어선이다.

Max iteration core policy는 Agent 무한 반복을 막는 반복 허용 여부 판단이다.
반복 횟수를 공식적으로 제공하는 Agent State가 확정되면 ``before_model``
lifecycle adapter로 연결한다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any, TypeVar

from langchain.agents.middleware import HumanInTheLoopMiddleware, wrap_tool_call
from models.schemas import ErrorCode, PendingAction, RuntimeContext

T = TypeVar("T")
MAX_TOOL_ATTEMPTS = 3
RETRYABLE_ERROR_CODES = frozenset({"API_TIMEOUT", "API_RATE_LIMIT", "API_RESPONSE_ERROR"})
NON_RETRYABLE_ERROR_CODES = frozenset({
    "API_AUTH_ERROR", "API_BAD_REQUEST", "INVALID_INPUT", "UNSUPPORTED_AREA",
    "AREA_NOT_FOUND", "STATION_NOT_FOUND", "NO_DATA", "MISSING_REQUIRED_INPUT",
    "TOOL_INTERNAL_ERROR",
})
SENSITIVE_ACTION_TOOL_TYPES = {
    "send_analysis_report": "send_report",
}


class SensitiveActionExecutionDenied(PermissionError):
    """외부 행동의 실행 전 승인 검증이 실패했을 때 발생한다."""


class MaxIterationReached(RuntimeError):
    """Agent 반복 한도에 도달했음을 공통 ErrorCode와 함께 알린다."""

    error_code = ErrorCode.MAX_ITERATION_REACHED


def _get_success(result: Any) -> bool | None:
    result = _tool_result_payload(result)
    return result.get("success") if isinstance(result, Mapping) else getattr(result, "success", None)


def _get_error_code(result: Any) -> str | None:
    result = _tool_result_payload(result)
    value = result.get("error_code") if isinstance(result, Mapping) else getattr(result, "error_code", None)
    return value if isinstance(value, str) else None


def _get_error_message(result: Any) -> str | None:
    result = _tool_result_payload(result)
    value = result.get("error_message") if isinstance(result, Mapping) else getattr(result, "error_message", None)
    return value if isinstance(value, str) else None


def _tool_result_payload(result: Any) -> Any:
    """ToolMessage content의 JSON ToolResult도 공통 모델 병합 전부터 읽는다."""
    if isinstance(result, Mapping) or hasattr(result, "success"):
        return result
    content = getattr(result, "content", None)
    if not isinstance(content, str):
        return result
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return result
    return payload if isinstance(payload, Mapping) else result


def should_retry(result_or_exception: Any) -> bool:
    """일시적 ToolResult 실패와 timeout 예외만 재시도한다."""
    if isinstance(result_or_exception, TimeoutError):
        return True
    error_code = _get_error_code(result_or_exception)
    if error_code in NON_RETRYABLE_ERROR_CODES:
        return False
    return _get_success(result_or_exception) is False and error_code in RETRYABLE_ERROR_CODES


def _preserve_mock_failure_provenance(mock_result: T, failure: Any) -> T:
    """공통 ToolResult가 허용한 Mock fallback provenance만 최종 결과에 남긴다."""
    error_code = _get_error_code(failure)
    if error_code is None:
        return mock_result
    error_message = _get_error_message(failure)

    if hasattr(mock_result, "content") and isinstance(mock_result.content, str):
        payload = _tool_result_payload(mock_result)
        if isinstance(payload, Mapping) and payload.get("success") is True and payload.get("is_mock") is True:
            updated = dict(payload)
            updated["error_code"] = error_code
            if error_message is not None:
                updated["error_message"] = error_message
            return mock_result.model_copy(update={"content": json.dumps(updated, ensure_ascii=False)})

    return mock_result


# 데이터 부재/미지원 지역은 Mock으로 성공 처리하지 않는다.
# 실제 저장소는 이 모듈이 소유하지 않고 cache/mock provider로 주입받는다.
def execute_with_retry(operation: Callable[..., T], *args: Any, cache_provider: Callable[..., T | None] | None = None, mock_provider: Callable[..., T | None] | None = None, **kwargs: Any) -> T:
    """최대 세 번 실행하고, 소진 시 cache → mock을 적용한다.

    provider는 operation과 같은 인자를 받는다. 비재시도 오류는 fallback하지 않아
    ``NO_DATA`` 등을 임의 Mock 값으로 바꾸지 않는다.
    """
    last_failure: T | Exception | None = None
    for attempt in range(MAX_TOOL_ATTEMPTS):
        try:
            result = operation(*args, **kwargs)
        except Exception as exc:
            if not should_retry(exc):
                raise
            last_failure = exc
        else:
            if not should_retry(result):
                return result
            last_failure = result
        if attempt == MAX_TOOL_ATTEMPTS - 1:
            break
    if cache_provider is not None:
        cached = cache_provider(*args, **kwargs)
        if cached is not None:
            return cached
    if mock_provider is not None:
        mocked = mock_provider(*args, **kwargs)
        if mocked is not None:
            return _preserve_mock_failure_provenance(mocked, last_failure)
    if isinstance(last_failure, Exception):
        raise last_failure
    if last_failure is None:
        raise RuntimeError("retry operation produced no result")
    return last_failure


def create_tool_retry_middleware(*, cache_provider: Callable[..., Any | None] | None = None, mock_provider: Callable[..., Any | None] | None = None) -> Any:
    """Agent 통합 시 provider를 주입할 수 있는 얇은 ``wrap_tool_call`` adapter."""
    @wrap_tool_call
    def retry_tool_call(request: Any, handler: Callable[[Any], Any]) -> Any:
        return execute_with_retry(handler, request, cache_provider=cache_provider, mock_provider=mock_provider)
    return retry_tool_call


@wrap_tool_call
def tool_retry_middleware(request: Any, handler: Callable[[Any], Any]) -> Any:
    """기본 Tool wrapper; ToolResult 직렬화 방식 확정 후 Agent에서 연결한다."""
    return execute_with_retry(handler, request)


def build_human_in_the_loop_middleware() -> HumanInTheLoopMiddleware:
    """checkpointer 기반의 승인 전에는 action Tool을 실행하지 않게 구성한다."""
    return HumanInTheLoopMiddleware({
        "send_analysis_report": {"allowed_decisions": ["approve", "reject"]},
    })


def ensure_sensitive_action_approved(
    tool_name: str,
    pending_action: PendingAction | None,
    runtime_context: RuntimeContext,
) -> None:
    """실제 action Tool 호출 직전에 저장된 승인 상태와 실행 주체를 검증한다."""
    expected_action_type = SENSITIVE_ACTION_TOOL_TYPES.get(tool_name)
    if expected_action_type is None:
        raise ValueError(f"지원하지 않는 sensitive action tool: {tool_name}")
    if pending_action is None:
        raise SensitiveActionExecutionDenied("승인 대기 작업이 없어 외부 행동을 실행할 수 없습니다")
    if pending_action.status != "approved":
        raise SensitiveActionExecutionDenied("승인된 작업만 외부 행동을 실행할 수 있습니다")
    if pending_action.action_type != expected_action_type:
        raise SensitiveActionExecutionDenied("승인된 작업과 실행 Tool이 일치하지 않습니다")
    if pending_action.user_id != runtime_context.user_id:
        raise SensitiveActionExecutionDenied("승인한 사용자와 실행 사용자가 일치하지 않습니다")
    if pending_action.session_id != runtime_context.session_id:
        raise SensitiveActionExecutionDenied("승인한 세션과 실행 세션이 일치하지 않습니다")


def _pending_action_from_state(state: Any) -> PendingAction | None:
    pending_action = state.get("pending_action") if isinstance(state, Mapping) else getattr(state, "pending_action", None)
    return pending_action if isinstance(pending_action, PendingAction) else None


@wrap_tool_call
def sensitive_action_execution_guard(request: Any, handler: Callable[[Any], Any]) -> Any:
    """LangChain Tool 실행 경계에서 sensitive action만 defense-in-depth 검증한다."""
    tool_name = request.tool_call["name"]
    if tool_name not in SENSITIVE_ACTION_TOOL_TYPES:
        return handler(request)
    runtime_context = getattr(request.runtime, "context", None)
    if not isinstance(runtime_context, RuntimeContext):
        raise SensitiveActionExecutionDenied("신뢰 가능한 실행 주체 정보가 필요합니다")
    ensure_sensitive_action_approved(
        tool_name,
        _pending_action_from_state(request.state),
        runtime_context,
    )
    # TODO: action Tool interface가 action_id/payload_version을 전달하면 승인 대상과도 비교한다.
    return handler(request)


def can_continue_agent_iteration(current_iteration: int, max_iterations: int) -> bool:
    """현재 반복이 Agent의 추가 Model/Tool 호출 한도 안에 있는지 판정한다."""
    if current_iteration < 0:
        raise ValueError("current_iteration은 0 이상이어야 합니다")
    if max_iterations <= 0:
        raise ValueError("max_iterations는 1 이상이어야 합니다")
    return current_iteration < max_iterations


def ensure_agent_iteration_available(current_iteration: int, max_iterations: int) -> None:
    """한도 도달 시 추가 호출을 막고 MAX_ITERATION_REACHED를 식별 가능하게 한다."""
    if not can_continue_agent_iteration(current_iteration, max_iterations):
        raise MaxIterationReached("Agent 최대 반복 횟수에 도달했습니다")


# TODO: 현재 before_model state/runtime에는 안정적인 iteration count가 없다.
# Agent가 해당 값을 공식 State로 제공하면 이 policy를 before_model adapter에 연결한다.
