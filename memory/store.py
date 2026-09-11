"""StudySpot 장기 Memory(Store) 관리.

담당: 역할 2 · 소유 · feature/memory
명세: docs/02_Memory.md

- 세션을 넘어 유지할 사용자 선호와 관심 상권만 저장한다.
- 저장 대상: 예산, 타깃 연령, 선호 지역, 평가 우선순위, 관심 상권.
- Tool 이름은 save_user_preferences, save_shortlist로 고정한다.
- user_id는 RuntimeContext에서 주입하며 사용자 입력이나 LLM이 지정하지 않는다.
- 선호 정보는 사용자가 명시적으로 저장을 요청하거나 동의한 경우에만 저장한다.
- 사용자별 namespace를 사용해 장기 Memory를 분리한다.
"""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any

from langchain.tools import ToolRuntime, tool
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from pydantic import ValidationError

from models.schemas import (
    ErrorCode,
    RuntimeContext,
    ToolResult,
    UserPreferences,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Store 설정
# ---------------------------------------------------------------------------

# MVP용 InMemory Store.
# 프로세스가 재시작되면 저장 데이터가 사라진다.
memory_store = InMemoryStore()

# 동일 프로세스 안에서 get → 수정 → put이 겹쳐 갱신값이 유실되는 것을 줄인다.
# 실제 운영 DB에서는 트랜잭션/원자적 갱신으로 대체해야 한다.
_store_lock = RLock()

_PREFERENCE_KEY = "preferences"

_ALLOWED_PREFERENCE_FIELDS = {
    "preferred_regions",
    "deposit_budget",
    "monthly_rent_budget",
    "target_age",
    "priority_metrics",
}


class MemoryStoreError(RuntimeError):
    """장기 Memory 저장소 접근 또는 저장 데이터 검증 실패."""


def _namespace(context: RuntimeContext) -> tuple[str, ...]:
    """사용자별 Store namespace를 만든다."""

    return (
        "studyspot",
        "users",
        context.user_id,
    )


def _resolve_store(store: BaseStore | None) -> BaseStore:
    return store if store is not None else memory_store


# ---------------------------------------------------------------------------
# 내부 조회
# ---------------------------------------------------------------------------

def load_user_preferences(
    context: RuntimeContext,
    store: BaseStore | None = None,
) -> UserPreferences | None:
    """사용자의 장기 선호를 조회한다.

    Returns:
        UserPreferences: 저장된 선호가 존재함
        None: 정상 조회됐지만 저장된 선호가 없음

    Raises:
        MemoryStoreError: Store 장애 또는 저장 데이터가 잘못된 경우
    """

    selected_store = _resolve_store(store)

    try:
        item = selected_store.get(
            _namespace(context),
            _PREFERENCE_KEY,
        )
    except Exception as exc:
        logger.exception("[MEMORY] 사용자 선호 조회 실패")
        raise MemoryStoreError(
            "사용자 선호 저장소 조회에 실패했습니다."
        ) from exc

    if item is None:
        logger.debug("[MEMORY] 저장된 사용자 선호 없음")
        return None

    try:
        preferences = UserPreferences.model_validate(item.value)
    except (ValidationError, TypeError, ValueError) as exc:
        logger.exception("[MEMORY] 저장 데이터 검증 실패")
        raise MemoryStoreError(
            "저장된 사용자 선호 데이터가 올바르지 않습니다."
        ) from exc

    # namespace와 저장 모델의 user_id가 어긋난 데이터는 사용하지 않는다.
    if preferences.user_id != context.user_id:
        logger.error("[MEMORY] 사용자 namespace 불일치")
        raise MemoryStoreError(
            "저장된 사용자 정보의 소유자를 확인할 수 없습니다."
        )

    return preferences


def _empty_preferences(context: RuntimeContext) -> UserPreferences:
    """아직 장기 선호가 없는 사용자의 빈 모델을 만든다."""

    return UserPreferences(
        user_id=context.user_id,
    )


# ---------------------------------------------------------------------------
# 선호 저장 내부 함수
# ---------------------------------------------------------------------------

def save_user_preferences_data(
    preferences: dict[str, Any],
    context: RuntimeContext,
    store: BaseStore | None = None,
) -> ToolResult:
    """허용된 사용자 선호만 병합 저장한다."""

    selected_store = _resolve_store(store)

    if not preferences:
        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.INVALID_INPUT,
            error_message="저장할 사용자 선호가 없습니다.",
            is_mock=False,
        )

    unknown_fields = set(preferences) - _ALLOWED_PREFERENCE_FIELDS

    if unknown_fields:
        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.INVALID_INPUT,
            error_message="저장할 수 없는 사용자 선호 필드가 포함되어 있습니다.",
            is_mock=False,
        )

    try:
        with _store_lock:
            current = (
                load_user_preferences(context, selected_store)
                or _empty_preferences(context)
            )

            merged = current.model_dump()

            # dict에 실제 포함된 필드만 수정한다.
            # deposit_budget=None 등은 명시적 초기화로 처리할 수 있다.
            for field_name, value in preferences.items():
                merged[field_name] = value

            # user_id는 항상 신뢰 가능한 RuntimeContext의 값을 사용한다.
            merged["user_id"] = context.user_id

            updated = UserPreferences.model_validate(merged)

            selected_store.put(
                _namespace(context),
                _PREFERENCE_KEY,
                updated.model_dump(mode="json"),
            )

    except (MemoryStoreError, ValidationError, TypeError, ValueError):
        logger.exception("[MEMORY] 사용자 선호 저장 실패")

        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message="사용자 선호를 저장하지 못했습니다.",
            is_mock=False,
        )

    except Exception:
        logger.exception("[MEMORY] 사용자 선호 저장소 오류")

        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message="사용자 선호 저장 중 오류가 발생했습니다.",
            is_mock=False,
        )

    logger.info(
        "[MEMORY] 사용자 선호 저장 완료 | fields=%s",
        sorted(preferences),
    )

    return ToolResult(
        success=True,
        source="memory_store",
        data={
            "saved_fields": sorted(preferences),
        },
        error_code=None,
        error_message=None,
        is_mock=False,
    )


# ---------------------------------------------------------------------------
# 관심 상권 저장 내부 함수
# ---------------------------------------------------------------------------

def save_shortlist_data(
    commercial_area_ids: list[str],
    context: RuntimeContext,
    store: BaseStore | None = None,
) -> ToolResult:
    """관심 상권 ID를 사용자 장기 Memory에 중복 없이 저장한다."""

    selected_store = _resolve_store(store)

    if not commercial_area_ids:
        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.INVALID_INPUT,
            error_message="저장할 관심 상권이 없습니다.",
            is_mock=False,
        )

    try:
        with _store_lock:
            current = (
                load_user_preferences(context, selected_store)
                or _empty_preferences(context)
            )

            # 입력 순서는 유지하면서 중복 ID를 제거한다.
            requested_ids = list(dict.fromkeys(commercial_area_ids))

            all_ids = list(
                dict.fromkeys(
                    [
                        *current.shortlisted_areas,
                        *requested_ids,
                    ]
                )
            )

            updated = current.model_copy(
                update={
                    "shortlisted_areas": all_ids,
                }
            )

            # model_copy는 update 값을 재검증하지 않으므로 최종 검증을 다시 수행한다.
            updated = UserPreferences.model_validate(
                updated.model_dump()
            )

            selected_store.put(
                _namespace(context),
                _PREFERENCE_KEY,
                updated.model_dump(mode="json"),
            )

    except (MemoryStoreError, ValidationError, TypeError, ValueError):
        logger.exception("[MEMORY] 관심 상권 저장 실패")

        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message="관심 상권을 저장하지 못했습니다.",
            is_mock=False,
        )

    except Exception:
        logger.exception("[MEMORY] 관심 상권 저장소 오류")

        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message="관심 상권 저장 중 오류가 발생했습니다.",
            is_mock=False,
        )

    logger.info(
        "[MEMORY] 관심 상권 저장 완료 | count=%d",
        len(requested_ids),
    )

    return ToolResult(
        success=True,
        source="memory_store",
        data={
            "saved_ids": requested_ids,
        },
        error_code=None,
        error_message=None,
        is_mock=False,
    )


# ---------------------------------------------------------------------------
# Agent가 호출하는 Memory Tools
# ---------------------------------------------------------------------------

@tool
def save_user_preferences(
    preferences: dict[str, Any],
    runtime: ToolRuntime[RuntimeContext],
) -> ToolResult:
    """사용자가 명시적으로 기억을 요청한 선호를 장기 Memory에 저장한다.

    저장 가능 필드:
    preferred_regions, deposit_budget, monthly_rent_budget,
    target_age, priority_metrics.

    user_id는 RuntimeContext에서만 가져온다.
    """

    if runtime.store is None:
        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message="장기 Memory Store가 연결되지 않았습니다.",
            is_mock=False,
        )

    return save_user_preferences_data(
        preferences=preferences,
        context=runtime.context,
        store=runtime.store,
    )


@tool
def save_shortlist(
    commercial_area_ids: list[str],
    runtime: ToolRuntime[RuntimeContext],
) -> ToolResult:
    """사용자가 선택한 관심 상권 ID를 장기 Memory에 저장한다.

    동일 commercial_area_id는 한 번만 저장한다.
    user_id는 RuntimeContext에서만 가져온다.
    """

    if runtime.store is None:
        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message="장기 Memory Store가 연결되지 않았습니다.",
            is_mock=False,
        )

    return save_shortlist_data(
        commercial_area_ids=commercial_area_ids,
        context=runtime.context,
        store=runtime.store,
    )