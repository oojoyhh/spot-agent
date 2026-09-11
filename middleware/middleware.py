"""Agent Graph의 외부 Tool 복구·승인 경계.

실행 흐름: 외부 Tool 호출 → retry 가능 여부 판정 → 최초 1회 + retry 최대
2회 → 실패 지속 시 cache → cache miss면 mock → 대체 수단도 없으면 원 실패
반환이다.

``should_retry``는 일시 장애와 영구/의미 없는 실패를 구분한다.
``execute_with_retry``는 framework-independent retry/fallback core이고,
``create_tool_retry_middleware`` 및 ``tool_retry_middleware``는 이를
LangChain ``wrap_tool_call``에 연결한다. ``build_human_in_the_loop_middleware``는
외부 부작용 Tool이 사용자 승인 전에 실행되지 않도록 구성한다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any, TypeVar

from langchain.agents.middleware import HumanInTheLoopMiddleware, wrap_tool_call

T = TypeVar("T")
MAX_TOOL_ATTEMPTS = 3
RETRYABLE_ERROR_CODES = frozenset({"API_TIMEOUT", "API_RATE_LIMIT", "API_RESPONSE_ERROR"})
NON_RETRYABLE_ERROR_CODES = frozenset({"API_AUTH_ERROR", "API_BAD_REQUEST", "INVALID_INPUT", "UNSUPPORTED_AREA", "AREA_NOT_FOUND", "NO_DATA"})


def _get_success(result: Any) -> bool | None:
    result = _tool_result_payload(result)
    return result.get("success") if isinstance(result, Mapping) else getattr(result, "success", None)


def _get_error_code(result: Any) -> str | None:
    result = _tool_result_payload(result)
    value = result.get("error_code") if isinstance(result, Mapping) else getattr(result, "error_code", None)
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


# 데이터 부재/미지원 지역은 Mock으로 성공 처리하지 않는다.
# 실제 저장소는 이 모듈이 소유하지 않고 cache/mock provider로 주입받는다.
def execute_with_retry(operation: Callable[..., T], *args: Any, cache_provider: Callable[..., T | None] | None = None, mock_provider: Callable[..., T] | None = None, **kwargs: Any) -> T:
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
        return mock_provider(*args, **kwargs)
    if isinstance(last_failure, Exception):
        raise last_failure
    if last_failure is None:
        raise RuntimeError("retry operation produced no result")
    return last_failure


def create_tool_retry_middleware(*, cache_provider: Callable[..., Any | None] | None = None, mock_provider: Callable[..., Any] | None = None) -> Any:
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
        "create_site_visit_event": {"allowed_decisions": ["approve", "reject"]},
    })


# TODO: Agent graph/recursion 정책이 확정된 뒤 MaxIterationMiddleware를 연결한다.
