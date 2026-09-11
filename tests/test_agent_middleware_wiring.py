"""Agent에 등록된 실제 wrapper를 외부 호출 없이 검증한다."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from agent import main_agent as agent
from models.schemas import ToolResult


CASES = [
    ('get_academy_demand', {'school_age': 'high'}),
    ('get_station_exit_traffic', {'station_id': '221'}),
    ('get_visitor_demographics', {'target_age': '20대'}),
    ('get_district_congestion', {}),
    ('search_competitors', {'radius_m': 500}),
]


def request_for(name, extra):
    # 실제 Agent Tool 입력 스키마와 Mock provider가 같은 인자를 받는다.
    args = {
        'area': {'commercial_area_id': '9307', 'administrative_code': '1168010100',
                 'area_name': '역삼역남부 3번출구', 'latitude': 37.5, 'longitude': 127.03},
        'period': {'start_date': '2026-09-10', 'end_date': '2026-09-10',
                   'day_types': ['weekday']},
        **extra,
    }
    tool = getattr(agent, name)
    fields = tool.args_schema.model_fields
    args = {key: value for key, value in args.items() if key in fields}
    tool.args_schema.model_validate(args)
    return SimpleNamespace(tool_call={'name': tool.name, 'id': 'test-call', 'args': args})


@pytest.mark.parametrize('name,extra', CASES)
@pytest.mark.parametrize('code', ['API_TIMEOUT', 'API_RATE_LIMIT', 'API_RESPONSE_ERROR'])
def test_registered_retry_falls_back_with_provenance(name, extra, code):
    request = request_for(name, extra)
    failure = ToolResult(success=False, is_mock=False, source='test-api', data={},
                         error_code=code, error_message='original failure')
    handler = Mock(return_value=ToolMessage(content=failure.model_dump_json(), tool_call_id='test-call'))
    result = agent.tool_retry_middleware.wrap_tool_call(request, handler)
    parsed = ToolResult.model_validate_json(result.content)
    assert handler.call_count == 3
    assert parsed.success and parsed.is_mock
    assert parsed.error_code == code
    assert parsed.error_message == 'original failure'
    assert result.name == name and result.tool_call_id == 'test-call'


@pytest.mark.parametrize('code', ['API_AUTH_ERROR', 'INVALID_INPUT', 'UNSUPPORTED_AREA', 'NO_DATA'])
def test_permanent_failure_is_not_hidden(code):
    request = request_for('get_academy_demand', {'school_age': 'high'})
    failure = ToolResult(success=False, is_mock=False, source='test-api', data={}, error_code=code, error_message='failure')
    message = ToolMessage(content=failure.model_dump_json(), tool_call_id='test-call')
    handler = Mock(return_value=message)
    assert agent.tool_retry_middleware.wrap_tool_call(request, handler) == message
    assert handler.call_count == 1


def test_agent_registers_guard_outside_retry(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent, 'create_agent', lambda **kwargs: captured.update(kwargs))
    agent.build_agent()
    middleware = captured['middleware']
    assert middleware.index(agent.require_analysis_conditions) < middleware.index(agent.tool_output_guardrail)
    assert middleware.index(agent.tool_output_guardrail) < middleware.index(agent.tool_retry_middleware)
    names = {tool.name for tool in captured['tools']}
    assert agent._MOCK_TOOL_NAMES == {name for name, _ in CASES}
    assert agent._MOCK_TOOL_NAMES <= names
    assert agent._agent_mock_provider(SimpleNamespace(tool_call={'name': 'resolve_area_entities'})) is None
    assert middleware.index(agent.collect_analysis_results) < middleware.index(agent.enforce_max_agent_iterations)


def _tool_history_state(error_code='NO_DATA'):
    call_id = 'call-no-data'
    return {
        'messages': [
            HumanMessage(content='분석해줘'),
            AIMessage(content='', tool_calls=[{
                'id': call_id, 'name': 'get_academy_demand', 'args': {},
            }]),
            ToolMessage(content='', tool_call_id=call_id, name='get_academy_demand'),
        ],
        'tool_results': {
            call_id: ToolResult(
                success=False, is_mock=False, source='test-api', data={},
                error_code=error_code, error_message='원본 오류',
            ),
        },
    }


def test_tool_call_mapping_and_no_data_reason_are_saved_for_final_response():
    state = _tool_history_state()

    assert agent.tool_call_name_mapping(state) == {'call-no-data': 'get_academy_demand'}
    assert agent._unavailable_data_reasons(state) == ['get_academy_demand (call-no-data): NO_DATA']


def test_execution_error_is_not_mislabeled_as_missing_data():
    assert agent._unavailable_data_reasons(_tool_history_state('API_TIMEOUT')) == []


def test_max_iteration_uses_messages_since_last_human_message_and_resets():
    old_turn = [HumanMessage(content='이전 요청')] + [AIMessage(content='') for _ in range(10)]
    state = {'messages': old_turn + [HumanMessage(content='새 요청')]}
    assert agent._current_iteration(state) == 0

    state['messages'].extend(AIMessage(content='') for _ in range(agent._MAX_AGENT_ITERATIONS))
    outcome = agent.enforce_max_agent_iterations.before_model(state, None)
    assert outcome['jump_to'] == 'end'
    assert outcome['missing_data'] == ['MAX_ITERATION_REACHED']
    assert outcome['structured_response']['status'] == 'no_result'
