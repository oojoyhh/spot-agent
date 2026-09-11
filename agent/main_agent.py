"""Agent 생성·Tool 등록·Memory/Middleware 연결.

담당: 역할 5 · 석휘 · feature/agent-core
명세: docs/05_Agent_Architecture.md

- 제안 진입점: run_analysis(request: AgentRequest, context: RuntimeContext) -> StudySpotResponse
- 실행 가능한 Tool만 등록한다. 미구현 Tool을 등록하지 않는다
- 모델 응답은 StudySpotResponse 검증 후 반환한다

현재 상태: Memory(단기 State·장기 Store) 연동 완료. 입력/출력 가드레일·PII·Tool
재시도 middleware 연동 완료. 분석용 Tool, 승인(HITL) 플로우는 아직 미구현.
"""

# 기본 유틸리티
import logging
from pathlib import Path

from dotenv import load_dotenv


# LangChain Agent 생성 함수
from langchain.agents import create_agent
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

# 프로젝트에서 작성된 시스템 프롬프트
from agent.prompts import SYSTEM_PROMPT

# Tool (임시) — 분석용 Tool은 아직 미구현이라 등록하지 않는다.
# 각 모듈의 Tool이 완성되면 실행 가능한 것만 골라 tools 리스트에 추가한다.
from tools import academy_tools, action_tools, market_tools, scoring_tools, subway_tools

# Memory — 단기 State(checkpointer)와 장기 Store는 이미 구현되어 있다.
from memory import (
    MemoryStoreError,
    build_new_session_conditions,
    build_thread_config,
    checkpointer as default_checkpointer,
    create_initial_state,
    load_user_preferences,
    memory_store as default_store,
    merge_business_conditions,
    save_shortlist,
    save_user_preferences,
)

# Middleware — 패키지 이름과 submodule 이름이 같아(middleware/middleware.py) 헷갈리지 않도록
# 필요한 이름만 submodule 경로로 직접 import한다.
from middleware.guardrails import (
    build_pii_middlewares,
    input_guardrail,
    output_secret_guardrail,
)
from middleware.middleware import tool_retry_middleware

# middleware.middleware.build_human_in_the_loop_middleware, sensitive_action_execution_guard는
# send_analysis_report/create_site_visit_event Tool이 구현된 뒤 tools·middleware에 함께 추가한다.

# Schemas
from models.schemas import AgentRequest, RuntimeContext, StudySpotResponse, StudySpotState


logger = logging.getLogger(__name__)


def build_agent(
    model_name: str = "gpt-5-mini",
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
) -> CompiledStateGraph:
    """지정한 모델과 시스템 프롬프트를 연결한 Agent를 반환합니다.

    model_name은 LangChain에서 사용할 모델 식별자입니다.
    checkpointer/store를 생략하면 memory 패키지의 기본 인스턴스를 사용한다
    (프로세스 전체에서 공유되는 InMemory 구현이므로 테스트 시에는 별도 인스턴스를 넘길 수 있다).

    - state_schema=StudySpotState: 창업 조건·분석 중간 결과를 State로 관리한다.
    - context_schema=RuntimeContext: save_user_preferences/save_shortlist 같은 Tool이
      ToolRuntime[RuntimeContext]로 user_id 등을 안전하게 받을 수 있게 한다.
    - response_format=StudySpotResponse: 모델의 최종 응답을 자동으로 검증한다
      (result["structured_response"]).

    middleware 순서는 guardrails.py의 실행 흐름 설명을 그대로 따른다:
    사용자 입력 → input_guardrail(위험 요청 차단) → PII 처리 → Agent/Model → 응답
    생성 후 output_secret_guardrail(내부정보 노출 차단). tool_retry_middleware는
    개별 Tool 호출(wrap_tool_call) 경계라 나머지와 실행 시점이 겹치지 않는다.
    """
    return create_agent(
        model=model_name,
        tools=[
            save_user_preferences,
            save_shortlist,
        ],
        middleware=[
            input_guardrail,  # before_agent: prompt injection·secret 요청·상세주소 차단
            *build_pii_middlewares(),  # 입출력 email/phone 마스킹
            output_secret_guardrail,  # after_model: 응답에 노출된 secret 치환
            tool_retry_middleware,  # wrap_tool_call: 일시 장애 재시도 (cache/mock 미연결)
            # TODO: build_human_in_the_loop_middleware(), sensitive_action_execution_guard는
            # send_analysis_report/create_site_visit_event Tool 구현 후 추가
        ],
        system_prompt=SYSTEM_PROMPT,
        state_schema=StudySpotState,
        context_schema=RuntimeContext,
        response_format=StudySpotResponse,
        checkpointer=checkpointer or default_checkpointer,
        store=store or default_store,
    )


def _prepare_session_state(agent: CompiledStateGraph, request: AgentRequest, context: RuntimeContext) -> dict:
    """세션 State를 준비한다.

    - 새 세션(thread에 저장된 State가 없음): 장기 선호 위에 이번 요청의 창업 조건을 얹어
      초기 State를 만든다.
    - 기존 세션: 이번 요청에 창업 조건이 있으면 기존 조건에 병합하고, 영향받는 분석 결과를
      함께 무효화한다 (memory.state.merge_business_conditions).

    반환값은 실제로 반영된 update 내용이다 (로깅/디버깅용, 비어 있을 수 있다).
    """
    thread_config = build_thread_config(context)
    snapshot = agent.get_state(thread_config)
    is_new_session = not snapshot.values

    if is_new_session:
        preferences = None
        try:
            preferences = load_user_preferences(context)
        except MemoryStoreError:
            logger.warning("[AGENT] 장기 선호 조회 실패, 선호 없이 새 세션을 시작한다", exc_info=True)

        initial_conditions = build_new_session_conditions(preferences, request.business_conditions)
        initial_state = create_initial_state(business_conditions=initial_conditions)
        agent.update_state(thread_config, initial_state)
        return dict(initial_state)

    if request.business_conditions is not None:
        update = merge_business_conditions(snapshot.values, request.business_conditions)
        if update:
            agent.update_state(thread_config, update)
        return update

    return {}


def run_analysis(request: AgentRequest, context: RuntimeContext) -> StudySpotResponse:
    """AgentRequest와 RuntimeContext를 받아 Agent를 실행하고 StudySpotResponse를 반환합니다.

    request: UI가 보낸 이번 턴의 입력 (message 또는 approval_decision 중 하나 이상).
    context: 신뢰 가능한 실행 계층이 주입하는 실행 주체 정보 (user_id·session_id·user_role).
    반환값은 create_agent(response_format=StudySpotResponse)가 검증한 structured_response다.

    주의: AgentRequest는 message 없이 approval_decision만 올 수도 있다 (승인/거절 처리).
    승인 플로우는 build_human_in_the_loop_middleware()가 미들웨어에 등록되고
    (현재는 대상 action Tool이 미구현이라 등록하지 않았다) LangGraph의 interrupt
    재개(Command(resume=...))로 연결되어야 동작한다. 그전까지는 미구현이다.
    """
    if request.approval_decision is not None:
        # TODO: send_analysis_report/create_site_visit_event Tool + HITL 미들웨어 연동 후 구현
        raise NotImplementedError("approval_decision 처리는 아직 구현되지 않았다.")

    user_message = (request.message or "").strip()
    if not user_message:
        raise ValueError("질문을 입력해 주세요.")

    agent = build_agent()

    # thread_id는 user_id:session_id 조합 (memory.state.build_thread_id 참고).
    thread_config = build_thread_config(context)

    # 창업 조건 반영(새 세션 초기화 또는 기존 조건 병합)을 메시지 실행 전에 먼저 끝낸다.
    _prepare_session_state(agent, request, context)

    raw_result = agent.invoke(
        {"messages": [{"role": "user", "content": user_message}]},
        config=thread_config,
        context=context,
    )

    # create_agent(response_format=StudySpotResponse)가 이미 StudySpotResponse로 검증해 담아준다.
    return raw_result["structured_response"]


if __name__ == "__main__":
    # 환경 변수 입력
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    example_request = AgentRequest(message="유저 메시지")
    example_context = RuntimeContext(
        user_id="dev-user",
        session_id="dev-session",
        user_role="owner",
    )

    result = run_analysis(example_request, example_context)
    print(result)
