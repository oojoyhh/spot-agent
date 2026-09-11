"""StudySpot Memory 단위 테스트."""

import pytest
from langchain.messages import HumanMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.store.memory import InMemoryStore

from memory.state import (
    build_new_session_conditions,
    build_summary_state_update,
    build_thread_id,
    create_initial_state,
    merge_business_conditions,
)
from memory.store import (
    MemoryStoreError,
    load_user_preferences,
    save_shortlist_data,
    save_user_preferences_data,
)
from models.schemas import (
    BusinessConditions,
    ErrorCode,
    PendingAction,
    RuntimeContext,
)


def make_context(
    user_id: str = "user_001",
    session_id: str = "session_001",
) -> RuntimeContext:
    return RuntimeContext(
        user_id=user_id,
        session_id=session_id,
        user_role="founder",
    )


def make_conditions() -> BusinessConditions:
    return BusinessConditions(
        preferred_region="강남구",
        deposit_budget=50_000_000,
        monthly_rent_budget=2_500_000,
        target_age="20대",
        operating_start_time="09:00",
        operating_end_time="23:00",
        priority_metrics=["academy_demand_score"],
    )


# ---------------------------------------------------------------------------
# MEM-01 / 같은 세션의 조건 유지
# ---------------------------------------------------------------------------

def test_partial_condition_update_keeps_existing_values():
    state = create_initial_state(make_conditions())

    updates = BusinessConditions(
        monthly_rent_budget=3_000_000,
    )

    state_update = merge_business_conditions(
        state,
        updates,
    )

    merged = state_update["business_conditions"]

    assert merged.preferred_region == "강남구"
    assert merged.monthly_rent_budget == 3_000_000
    assert merged.target_age == "20대"
    assert merged.operating_start_time == "09:00"


def test_same_session_has_same_thread_id():
    context = make_context()

    assert build_thread_id(context) == "user_001:session_001"
    assert build_thread_id(context) == build_thread_id(context)


def test_new_session_has_different_thread_id():
    context_a = make_context(session_id="session_A")
    context_b = make_context(session_id="session_B")

    assert build_thread_id(context_a) != build_thread_id(context_b)


# ---------------------------------------------------------------------------
# MEM-02 / 조건 변경 시 기존 분석 결과 무효화
# ---------------------------------------------------------------------------

def test_budget_change_invalidates_analysis_results():
    state = create_initial_state(make_conditions())

    state["current_candidates"] = []
    state["tool_results"] = {"call_001": "old_result"}  # type: ignore[dict-item]
    state["market_scores"] = {"AREA_001": "old_score"}  # type: ignore[dict-item]
    state["missing_data"] = ["old"]
    state["pending_action"] = None

    updates = BusinessConditions(
        monthly_rent_budget=3_000_000,
    )

    result = merge_business_conditions(state, updates)

    assert result["current_candidates"] == []
    assert result["tool_results"] == {}
    assert result["market_scores"] == {}
    assert result["missing_data"] == []
    assert result["pending_action"] is None

    # 지역 자체는 바뀌지 않았으므로 searched_areas는 초기화 대상이 아니다.
    assert "searched_areas" not in result


def test_region_change_also_invalidates_searched_areas():
    state = create_initial_state(make_conditions())

    result = merge_business_conditions(
        state,
        BusinessConditions(preferred_region="마포구"),
    )

    assert result["searched_areas"] == []
    assert result["tool_results"] == {}
    assert result["market_scores"] == {}


# ---------------------------------------------------------------------------
# priority_metrics 팀 최종 합의
# ---------------------------------------------------------------------------

def test_priority_change_keeps_analysis_but_clears_pending_action():
    state = create_initial_state(make_conditions())

    state["tool_results"] = {}
    state["market_scores"] = {}

    state["pending_action"] = PendingAction(
        action_id="action_001",
        action_type="send_report",
        payload_version=1,
        display_summary="분석 보고서 전송",
        status="pending",
        user_id="user_001",
        session_id="session_001",
    )

    result = merge_business_conditions(
        state,
        BusinessConditions(
            priority_metrics=["rent_score"],
        ),
    )

    # 점수/Tool 결과를 다시 계산하라는 초기화는 하지 않는다.
    assert "tool_results" not in result
    assert "market_scores" not in result

    # 다만 기존 승인 대기 작업은 무효화한다.
    assert result["pending_action"] is None


# ---------------------------------------------------------------------------
# MEM-03 / 새 세션 + 같은 사용자
# ---------------------------------------------------------------------------

def test_new_session_loads_preferences_without_old_analysis_state():
    store = InMemoryStore()
    context = make_context()

    save_result = save_user_preferences_data(
        {
            "preferred_regions": ["신촌"],
            "monthly_rent_budget": 3_000_000,
            "target_age": "20대",
        },
        context,
        store,
    )

    assert save_result.success is True

    preferences = load_user_preferences(
        context,
        store,
    )

    conditions = build_new_session_conditions(
        preferences,
        BusinessConditions(
            operating_start_time="09:00",
            operating_end_time="23:00",
        ),
    )

    state = create_initial_state(conditions)

    assert conditions.preferred_region == "신촌"
    assert conditions.monthly_rent_budget == 3_000_000
    assert conditions.target_age == "20대"

    # 장기 선호는 복원하지만 이전 분석 결과는 들어오지 않는다.
    assert state["tool_results"] == {}
    assert state["market_scores"] == {}
    assert state["current_candidates"] == []


def test_current_input_overrides_long_term_preferences():
    store = InMemoryStore()
    context = make_context()

    save_user_preferences_data(
        {
            "preferred_regions": ["신촌"],
            "monthly_rent_budget": 3_000_000,
        },
        context,
        store,
    )

    preferences = load_user_preferences(context, store)

    conditions = build_new_session_conditions(
        preferences,
        BusinessConditions(
            preferred_region="강남구",
            monthly_rent_budget=4_000_000,
        ),
    )

    assert conditions.preferred_region == "강남구"
    assert conditions.monthly_rent_budget == 4_000_000


# ---------------------------------------------------------------------------
# MEM-04 / 사용자별 Store 격리
# ---------------------------------------------------------------------------

def test_different_users_do_not_share_preferences():
    store = InMemoryStore()

    user_a = make_context(
        user_id="user_A",
        session_id="session_A",
    )
    user_b = make_context(
        user_id="user_B",
        session_id="session_B",
    )

    save_user_preferences_data(
        {
            "preferred_regions": ["강남구"],
        },
        user_a,
        store,
    )

    assert load_user_preferences(user_a, store) is not None
    assert load_user_preferences(user_b, store) is None


# ---------------------------------------------------------------------------
# MEM-05 / 요약 시 최신 구조화 조건 보존
# ---------------------------------------------------------------------------

def test_summary_update_only_changes_messages():
    update = build_summary_state_update(
        [HumanMessage(content="이전 대화 요약")]
    )

    assert set(update.keys()) == {"messages"}
    assert update["messages"][0].id == REMOVE_ALL_MESSAGES


# ---------------------------------------------------------------------------
# MEM-07 / 관심 상권 중복 제거
# ---------------------------------------------------------------------------

def test_shortlist_does_not_save_duplicate_area_ids():
    store = InMemoryStore()
    context = make_context()

    first = save_shortlist_data(
        ["AREA_001", "AREA_002"],
        context,
        store,
    )
    second = save_shortlist_data(
        ["AREA_001", "AREA_003"],
        context,
        store,
    )

    assert first.success is True
    assert second.success is True

    preferences = load_user_preferences(
        context,
        store,
    )

    assert preferences is not None
    assert preferences.shortlisted_areas == [
        "AREA_001",
        "AREA_002",
        "AREA_003",
    ]


# ---------------------------------------------------------------------------
# MEM-08 / 미등록과 저장소 장애 구분
# ---------------------------------------------------------------------------

def test_unregistered_user_returns_none():
    store = InMemoryStore()

    assert load_user_preferences(
        make_context(),
        store,
    ) is None


class BrokenStore:
    def get(self, *args, **kwargs):
        raise RuntimeError("forced store error")


def test_store_failure_is_not_treated_as_unregistered():
    with pytest.raises(MemoryStoreError):
        load_user_preferences(
            make_context(),
            BrokenStore(),  # type: ignore[arg-type]
        )


def test_save_store_failure_returns_tool_internal_error():
    result = save_user_preferences_data(
        {
            "preferred_regions": ["강남구"],
        },
        make_context(),
        BrokenStore(),  # type: ignore[arg-type]
    )

    assert result.success is False
    assert result.error_code == ErrorCode.TOOL_INTERNAL_ERROR


# ---------------------------------------------------------------------------
# MEM-09 / 명시적 초기화
# ---------------------------------------------------------------------------

def test_explicit_none_clears_nullable_condition():
    state = create_initial_state(make_conditions())

    update = merge_business_conditions(
        state,
        BusinessConditions(
            monthly_rent_budget=None,
        ),
    )

    assert update["business_conditions"].monthly_rent_budget is None
    assert update["market_scores"] == {}


def test_multiple_saved_regions_are_not_arbitrarily_selected():
    store = InMemoryStore()
    context = make_context()

    save_user_preferences_data(
        {
            "preferred_regions": [
                "강남구",
                "마포구",
            ],
        },
        context,
        store,
    )

    preferences = load_user_preferences(
        context,
        store,
    )

    conditions = build_new_session_conditions(
        preferences,
    )

    assert conditions.preferred_region is None