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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from models.schemas import (
    ErrorCode,
    RuntimeContext,
    ScoreName,
    ToolResult,
    UserPreferences,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool 입력 스키마
# ---------------------------------------------------------------------------

class PreferenceUpdate(BaseModel):
    """save_user_preferences Tool의 입력 스키마.

    OpenAI strict Tool schema와 호환되도록 저장 가능한 필드를
    명시적으로 선언한다.

    값이 None이면 해당 선호는 이번 저장 요청에서 변경하지 않는다.
    user_id는 Tool 입력으로 받지 않고 RuntimeContext에서 가져온다.
    """

    model_config = ConfigDict(extra="forbid")

    preferred_regions: list[str] | None = None
    deposit_budget: int | None = Field(default=None, ge=0)
    monthly_rent_budget: int | None = Field(default=None, ge=0)
    target_age: str | None = None
    priority_metrics: list[ScoreName] | None = None


# ---------------------------------------------------------------------------
# Store 설정
# ---------------------------------------------------------------------------

# MVP용 InMemory Store.
# Python/Streamlit 프로세스가 재시작되면 저장 데이터는 초기화된다.
memory_store = InMemoryStore()

# 동일 프로세스 안에서 get → 수정 → put이 동시에 수행될 때
# 갱신값이 유실되는 것을 줄이기 위한 간단한 Lock.
# 운영 환경에서는 DB 트랜잭션 등으로 대체한다.
_store_lock = RLock()

_PREFERENCE_KEY = "preferences"

# Long-term Memory에 저장할 수 있는 사용자 선호 필드.
_ALLOWED_PREFERENCE_FIELDS = {
    "preferred_regions",
    "deposit_budget",
    "monthly_rent_budget",
    "target_age",
    "priority_metrics",
}


class MemoryStoreError(RuntimeError):
    """장기 Memory 저장소 접근 또는 저장 데이터 검증 실패."""


# ---------------------------------------------------------------------------
# Namespace / Store 공통 처리
# ---------------------------------------------------------------------------

def _namespace(context: RuntimeContext) -> tuple[str, ...]:
    """사용자별 Store namespace를 만든다."""

    return (
        "studyspot",
        "users",
        context.user_id,
    )


def _resolve_store(store: BaseStore | None) -> BaseStore:
    """외부 Store가 없으면 기본 InMemoryStore를 사용한다."""

    return store if store is not None else memory_store


def _empty_preferences(
    context: RuntimeContext,
) -> UserPreferences:
    """아직 장기 선호가 없는 사용자의 빈 선호 모델을 만든다."""

    return UserPreferences(
        user_id=context.user_id,
    )


# ---------------------------------------------------------------------------
# 사용자 선호 조회
# ---------------------------------------------------------------------------

def load_user_preferences(
    context: RuntimeContext,
    store: BaseStore | None = None,
) -> UserPreferences | None:
    """사용자의 장기 선호를 조회한다.

    Returns:
        UserPreferences:
            저장된 사용자 선호가 존재하는 경우.

        None:
            Store 조회는 정상적으로 수행됐지만
            아직 저장된 사용자 선호가 없는 경우.

    Raises:
        MemoryStoreError:
            Store 접근 실패 또는 저장 데이터 검증 실패.
    """

    selected_store = _resolve_store(store)

    try:
        item = selected_store.get(
            _namespace(context),
            _PREFERENCE_KEY,
        )

    except Exception as exc:
        logger.exception(
            "[MEMORY] 사용자 선호 조회 실패"
        )
        raise MemoryStoreError(
            "사용자 선호 저장소 조회에 실패했습니다."
        ) from exc

    if item is None:
        logger.debug(
            "[MEMORY] 저장된 사용자 선호 없음"
        )
        return None

    try:
        preferences = UserPreferences.model_validate(
            item.value
        )

    except (ValidationError, TypeError, ValueError) as exc:
        logger.exception(
            "[MEMORY] 저장 데이터 검증 실패"
        )
        raise MemoryStoreError(
            "저장된 사용자 선호 데이터가 올바르지 않습니다."
        ) from exc

    # namespace의 user_id와 저장된 데이터의 user_id가
    # 다르면 다른 사용자의 Memory일 가능성이 있으므로 사용하지 않는다.
    if preferences.user_id != context.user_id:
        logger.error(
            "[MEMORY] 사용자 namespace 불일치"
        )
        raise MemoryStoreError(
            "저장된 사용자 정보의 소유자를 확인할 수 없습니다."
        )

    return preferences


# ---------------------------------------------------------------------------
# 사용자 선호 저장 내부 로직
# ---------------------------------------------------------------------------

def save_user_preferences_data(
    preferences: dict[str, Any],
    context: RuntimeContext,
    store: BaseStore | None = None,
) -> ToolResult:
    """허용된 사용자 선호를 기존 장기 Memory와 병합 저장한다.

    이 함수는 Agent Tool의 내부 저장 로직이다.
    외부 Tool 인터페이스에서는 PreferenceUpdate 모델을 사용한다.
    """

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

    unknown_fields = (
        set(preferences)
        - _ALLOWED_PREFERENCE_FIELDS
    )

    if unknown_fields:
        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.INVALID_INPUT,
            error_message=(
                "저장할 수 없는 사용자 선호 필드가 포함되어 있습니다."
            ),
            is_mock=False,
        )

    try:
        with _store_lock:
            current = (
                load_user_preferences(
                    context,
                    selected_store,
                )
                or _empty_preferences(context)
            )

            merged = current.model_dump()

            # 이번 요청에서 실제 저장할 값만 기존 선호에 덮어쓴다.
            for field_name, value in preferences.items():
                merged[field_name] = value

            # user_id는 LLM 입력을 신뢰하지 않고
            # RuntimeContext 값으로 항상 고정한다.
            merged["user_id"] = context.user_id

            updated = UserPreferences.model_validate(
                merged
            )

            selected_store.put(
                _namespace(context),
                _PREFERENCE_KEY,
                updated.model_dump(mode="json"),
            )

    except (
        MemoryStoreError,
        ValidationError,
        TypeError,
        ValueError,
    ):
        logger.exception(
            "[MEMORY] 사용자 선호 저장 실패"
        )

        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message=(
                "사용자 선호를 저장하지 못했습니다."
            ),
            is_mock=False,
        )

    except Exception:
        logger.exception(
            "[MEMORY] 사용자 선호 저장소 오류"
        )

        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message=(
                "사용자 선호 저장 중 오류가 발생했습니다."
            ),
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
# 관심 상권 저장 내부 로직
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
                load_user_preferences(
                    context,
                    selected_store,
                )
                or _empty_preferences(context)
            )

            # 이번 요청 안의 중복 제거.
            # 순서는 사용자가 전달한 순서를 유지한다.
            requested_ids = list(
                dict.fromkeys(commercial_area_ids)
            )

            # 기존 관심 상권과 합치면서 다시 중복 제거.
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

            # model_copy(update=...)는 update 값을 재검증하지 않으므로
            # 최종적으로 UserPreferences 검증을 한 번 더 수행한다.
            updated = UserPreferences.model_validate(
                updated.model_dump()
            )

            selected_store.put(
                _namespace(context),
                _PREFERENCE_KEY,
                updated.model_dump(mode="json"),
            )

    except (
        MemoryStoreError,
        ValidationError,
        TypeError,
        ValueError,
    ):
        logger.exception(
            "[MEMORY] 관심 상권 저장 실패"
        )

        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message=(
                "관심 상권을 저장하지 못했습니다."
            ),
            is_mock=False,
        )

    except Exception:
        logger.exception(
            "[MEMORY] 관심 상권 저장소 오류"
        )

        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message=(
                "관심 상권 저장 중 오류가 발생했습니다."
            ),
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
    preferences: PreferenceUpdate,
    runtime: ToolRuntime[RuntimeContext],
) -> ToolResult:
    """사용자가 명시적으로 기억을 요청한 선호를 장기 Memory에 저장한다.

    저장 가능한 항목:
    - preferred_regions
    - deposit_budget
    - monthly_rent_budget
    - target_age
    - priority_metrics

    user_id는 Tool 입력으로 받지 않고
    RuntimeContext에서만 가져온다.
    """

    if runtime.store is None:
        return ToolResult(
            success=False,
            source="memory_store",
            data={},
            error_code=ErrorCode.TOOL_INTERNAL_ERROR,
            error_message=(
                "장기 Memory Store가 연결되지 않았습니다."
            ),
            is_mock=False,
        )

    # OpenAI strict Tool schema에서는 nullable 필드가
    # None으로 전달될 수 있으므로 실제 값이 있는 필드만 저장한다.
    preference_data = preferences.model_dump(
        exclude_none=True
    )

    return save_user_preferences_data(
        preferences=preference_data,
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
            error_message=(
                "장기 Memory Store가 연결되지 않았습니다."
            ),
            is_mock=False,
        )

    return save_shortlist_data(
        commercial_area_ids=commercial_area_ids,
        context=runtime.context,
        store=runtime.store,
    )
