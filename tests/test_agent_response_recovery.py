"""Agent/UI boundary regression tests for structured-output failures."""

from types import SimpleNamespace

from langchain.agents.structured_output import StructuredOutputValidationError
from langchain.messages import AIMessage

from agent import main_agent
from models.schemas import (
    AgentRequest,
    AreaRecommendation,
    BusinessConditions,
    EvidenceItem,
    RuntimeContext,
)


def _context() -> RuntimeContext:
    return RuntimeContext(user_id="test-user", session_id="test-session", user_role="analyst")


def _complete_conditions() -> BusinessConditions:
    return BusinessConditions(
        preferred_region="서울 은평구",
        deposit_budget=40_000_000,
        monthly_rent_budget=2_500_000,
        target_age="20대",
        operating_start_time="09:00",
        operating_end_time="23:00",
    )


def _recommendation() -> AreaRecommendation:
    return AreaRecommendation(
        commercial_area_id="TEST-AREA",
        area_name="테스트 상권",
        academy_demand_score=20,
        target_customer_score=15,
        station_traffic_score=10,
        activity_score=10,
        rent_score=10,
        competition_score=5,
        total_score=70,
        confidence=0.8,
        strengths=["검증된 점수 결과"],
        risks=[],
        evidence=[EvidenceItem(source="test", summary="테스트 근거", is_mock=True)],
    )


class _FakeAgent:
    def __init__(self, state: dict, *, fail_structured_output: bool = False) -> None:
        self.state = state
        self.fail_structured_output = fail_structured_output
        self.invoked = False

    def get_state(self, _config: dict) -> SimpleNamespace:
        return SimpleNamespace(values=self.state)

    def invoke(self, *_args, **_kwargs):
        self.invoked = True
        if self.fail_structured_output:
            raise StructuredOutputValidationError(
                "StudySpotResponse",
                ValueError("invalid status combination"),
                AIMessage(content=""),
            )
        raise AssertionError("invoke should not be called")


def _skip_state_setup(monkeypatch) -> None:
    monkeypatch.setattr(main_agent, "_invalidate_pending", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_agent, "_prepare_session_state", lambda *_args, **_kwargs: {})


def test_missing_conditions_return_before_model_call(monkeypatch) -> None:
    _skip_state_setup(monkeypatch)
    conditions = BusinessConditions(preferred_region="서울 은평구")
    agent = _FakeAgent({"business_conditions": conditions})

    response = main_agent.run_analysis(
        AgentRequest(message="분석해줘", business_conditions=conditions),
        _context(),
        agent=agent,
        store=object(),
    )

    assert response.status == "need_more_information"
    assert "monthly_rent_budget" in response.missing_required_inputs
    assert agent.invoked is False


def test_invalid_structured_output_recovers_verified_recommendations(monkeypatch) -> None:
    _skip_state_setup(monkeypatch)
    recommendation = _recommendation()
    monkeypatch.setattr(main_agent, "_recommendations", lambda _state: [recommendation])
    agent = _FakeAgent(
        {"business_conditions": _complete_conditions()},
        fail_structured_output=True,
    )

    response = main_agent.run_analysis(
        AgentRequest(message="분석해줘", business_conditions=_complete_conditions()),
        _context(),
        agent=agent,
        store=object(),
    )

    assert response.status == "success"
    assert response.recommendations == [recommendation]
    assert "자동 복구" in response.message
