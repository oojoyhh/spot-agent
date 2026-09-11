"""StudySpot 단기 Memory: State 갱신·요약·체크포인트 관리.

담당: 역할 2 · 소유 · feature/memory
명세: docs/02_Memory.md

- StudySpotState는 models/schemas.py에서 import한다.
- 현재 세션의 창업 조건과 분석 중간 결과를 State에 관리한다.
- 조건 변경 시 영향받는 기존 분석 결과를 무효화한다.
- 긴 대화는 요약하되 최신 창업 조건은 구조화된 State에 유지한다.
- user_id와 session_id를 조합한 thread_id로 세션을 분리한다.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from langchain.messages import RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from models.schemas import (
    STATE_CHECKPOINT_TYPES,
    BusinessConditions,
    MarketScore,
    RuntimeContext,
    StudySpotState,
    ToolResult,
    UserPreferences,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Short-term Memory / Checkpointer
# ---------------------------------------------------------------------------

# State 안의 Pydantic 모델을 경고 없이 저장·복원하기 위해
# 공통 schemas.py에서 정의한 허용 타입을 사용한다.
checkpointer = InMemorySaver(
    serde=JsonPlusSerializer(
        allowed_msgpack_modules=STATE_CHECKPOINT_TYPES
    )
)


def build_thread_id(context: RuntimeContext) -> str:
    """사용자와 세션을 조합해 단기 Memory 식별자를 만든다."""

    return f"{context.user_id}:{context.session_id}"


def build_thread_config(context: RuntimeContext) -> RunnableConfig:
    """Agent 호출 시 사용할 thread 설정을 만든다."""

    return {
        "configurable": {
            "thread_id": build_thread_id(context),
        }
    }


# ---------------------------------------------------------------------------
# 새 세션 초기화
# ---------------------------------------------------------------------------

def create_initial_state(
    business_conditions: BusinessConditions | None = None,
    messages: list[Any] | None = None,
) -> StudySpotState:
    """새 세션에서 사용할 초기 State를 만든다.

    이전 세션의 후보·Tool 결과·점수·승인 상태는 가져오지 않는다.
    """

    logger.info("[STATE] 새 세션 초기화")

    state = {
        "messages": list(messages or []),
        "business_conditions": business_conditions or BusinessConditions(),
        "searched_areas": [],
        "current_candidates": [],
        "tool_results": {},
        "market_scores": {},
        "missing_data": [],
        "pending_action": None,
    }

    return cast(StudySpotState, state)


# ---------------------------------------------------------------------------
# Long-term Preference → 새 세션 기본 조건
# ---------------------------------------------------------------------------

def conditions_from_preferences(
    preferences: UserPreferences | None,
) -> BusinessConditions:
    """장기 선호를 새 세션의 기본 창업 조건으로 변환한다.

    preferred_regions가 하나일 때만 preferred_region으로 자동 적용한다.
    여러 지역이 저장되어 있으면 임의로 하나를 고르지 않는다.

    운영 시간은 장기 선호 모델에 없으므로 새 세션에서 다시 입력받는다.
    """

    if preferences is None:
        return BusinessConditions()

    values: dict[str, Any] = {}

    if len(preferences.preferred_regions) == 1:
        values["preferred_region"] = preferences.preferred_regions[0]

    if preferences.deposit_budget is not None:
        values["deposit_budget"] = preferences.deposit_budget

    if preferences.monthly_rent_budget is not None:
        values["monthly_rent_budget"] = preferences.monthly_rent_budget

    if preferences.target_age is not None:
        values["target_age"] = preferences.target_age

    if preferences.priority_metrics:
        values["priority_metrics"] = list(preferences.priority_metrics)

    return BusinessConditions(**values)


def build_new_session_conditions(
    preferences: UserPreferences | None,
    current_input: BusinessConditions | None = None,
) -> BusinessConditions:
    """장기 선호 위에 이번 세션의 명시적 입력을 덮어쓴다.

    우선순위:
        현재 사용자 입력 > 장기 Store 선호
    """

    base = conditions_from_preferences(preferences)

    if current_input is None:
        return base

    values = base.model_dump()

    # model_fields_set을 사용해 이번 요청에서 실제 전달된 필드만 반영한다.
    for field_name in current_input.model_fields_set:
        values[field_name] = getattr(current_input, field_name)

    return BusinessConditions(**values)


# ---------------------------------------------------------------------------
# 현재 세션 조건 갱신
# ---------------------------------------------------------------------------

def merge_business_conditions(
    state: StudySpotState,
    updates: BusinessConditions,
) -> dict[str, Any]:
    """이번 Turn에서 명시적으로 전달된 조건만 기존 조건에 병합한다.

    예:
        기존: 강남 / 월세 250만원 / 20대
        입력: 월세 300만원
        결과: 강남 / 월세 300만원 / 20대

    반환값은 Agent State에 적용할 partial update다.
    """

    current = state.get("business_conditions") or BusinessConditions()

    provided_fields = set(updates.model_fields_set)

    if not provided_fields:
        return {}

    merged_values = current.model_dump()
    changed_fields: set[str] = set()

    for field_name in provided_fields:
        new_value = getattr(updates, field_name)
        old_value = merged_values.get(field_name)

        if old_value != new_value:
            merged_values[field_name] = new_value
            changed_fields.add(field_name)

    if not changed_fields:
        return {}

    merged_conditions = BusinessConditions(**merged_values)

    logger.info(
        "[STATE] 창업 조건 변경 | fields=%s",
        sorted(changed_fields),
    )

    return _build_condition_change_update(
        merged_conditions=merged_conditions,
        changed_fields=changed_fields,
    )


def _build_condition_change_update(
    merged_conditions: BusinessConditions,
    changed_fields: set[str],
) -> dict[str, Any]:
    """변경된 조건의 영향 범위에 맞춰 기존 분석 결과를 무효화한다."""

    update: dict[str, Any] = {
        "business_conditions": merged_conditions,
    }

    # 희망 지역이 바뀌면 상권 검색부터 다시 수행한다.
    if "preferred_region" in changed_fields:
        update.update(
            {
                "searched_areas": [],
                "current_candidates": [],
                "tool_results": {},
                "market_scores": {},
                "missing_data": [],
                "pending_action": None,
            }
        )
        return update

    # 이 값들은 데이터 조회와 점수에 영향을 준다.
    analysis_fields = {
        "deposit_budget",
        "monthly_rent_budget",
        "target_age",
        "operating_start_time",
        "operating_end_time",
    }

    if changed_fields & analysis_fields:
        update.update(
            {
                # 희망 지역은 그대로이므로 searched_areas는 유지한다.
                "current_candidates": [],
                "tool_results": {},
                "market_scores": {},
                "missing_data": [],
                "pending_action": None,
            }
        )
        return update

    # 팀 합의:
    # priority_metrics는 설명용이라 재조회·재계산하지 않지만,
    # 조건이 바뀌었으므로 기존 승인 대기 작업은 무효화한다.
    if "priority_metrics" in changed_fields:
        update["pending_action"] = None

    return update


# ---------------------------------------------------------------------------
# 분석 결과 State 저장
# ---------------------------------------------------------------------------

def record_tool_result(
    state: StudySpotState,
    call_id: str,
    result: ToolResult,
) -> dict[str, Any]:
    """Tool 결과를 호출 ID별로 저장한다."""

    tool_results = dict(state.get("tool_results", {}))
    tool_results[call_id] = result

    logger.debug(
        "[STATE] Tool 결과 저장 | call_id=%s | success=%s",
        call_id,
        result.success,
    )

    return {
        "tool_results": tool_results,
    }


def record_market_score(
    state: StudySpotState,
    commercial_area_id: str,
    score: MarketScore,
) -> dict[str, Any]:
    """Scoring Tool이 계산한 점수를 State에 저장한다.

    Memory 모듈은 점수를 직접 계산하거나 수정하지 않는다.
    """

    market_scores = dict(state.get("market_scores", {}))
    market_scores[commercial_area_id] = score

    logger.debug(
        "[STATE] 점수 결과 저장 | commercial_area_id=%s",
        commercial_area_id,
    )

    return {
        "market_scores": market_scores,
    }


# ---------------------------------------------------------------------------
# 긴 대화 요약
# ---------------------------------------------------------------------------

def build_summary_state_update(
    summarized_messages: list[Any],
) -> dict[str, Any]:
    """기존 메시지를 요약 메시지로 교체하기 위한 State update를 만든다.

    business_conditions 등 구조화된 최신 조건은 수정하지 않는다.
    """

    logger.info(
        "[STATE] 요약 메시지 반영 | message_count=%d",
        len(summarized_messages),
    )

    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            *summarized_messages,
        ]
    }