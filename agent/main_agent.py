"""Agent 생성·Tool 등록·Memory/Middleware 연결.

담당: 역할 5 · 석휘 · feature/agent-core
명세: docs/05_Agent_Architecture.md

- 제안 진입점: run_analysis(request: AgentRequest, context: RuntimeContext) -> StudySpotResponse
- 실행 가능한 Tool만 등록한다. 미구현 Tool을 등록하지 않는다
- 모델 응답은 StudySpotResponse 검증 후 반환한다

현재 상태: schema 적용.
"""

# 기본 유틸리티
from pathlib import Path
from dotenv import load_dotenv


# LangChain Agent 생성 함수
from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

# 프로젝트에서  작성된 시스템 프롬프트
from agent.prompts import SYSTEM_PROMPT

# Tool (임시)
from tools import academy_tools, action_tools, market_tools, scoring_tools, subway_tools

# Memory
from memory import __all__

# Middleware
from middleware import guardrails, middleware

# Schemas
from models.schemas import AgentRequest, RuntimeContext, StudySpotResponse, StudySpotState


def build_agent(model_name: str = "gpt-5-mini") -> CompiledStateGraph:
        """지정한 모델과 예제 프롬프트를 연결한 Agent를 반환합니다.
        model_name은 LangChain에서 사용할 모델 식별자입니다.
        state_schema는 StudySpotState를 사용하고, response_format으로 StudySpotResponse를
        지정해 모델의 최종 응답이 자동으로 검증되도록 한다 (result["structured_response"]).
        """

        return create_agent(
                model="gpt-5-mini",
                tools=[], # tool 채워야 함
                middleware=[], # middleware 채워야 함
                system_prompt=SYSTEM_PROMPT,
                state_schema=StudySpotState,
                response_format=StudySpotResponse,
        )

def run_analysis(request: AgentRequest, context: RuntimeContext) -> StudySpotResponse:
    """AgentRequest와 RuntimeContext를 받아 Agent를 실행하고 StudySpotResponse를 반환합니다.

    request: 사용자 질문 등 요청 정보를 담은 객체입니다.
    context: 모델 식별자, 세션/스레드 정보 등 실행 컨텍스트입니다.
    반환값은 create_agent(response_format=StudySpotResponse)가 검증한 structured_response다.

    """
    if request.approval_decision is not None:
                # 승인 거절 처리 -> 가드레일 연동 후 구현
                raise NotImplementedError("approval_decision 처리 구현 안 됨")

    user_message = (request.message or "").strip()
    if not user_message:
           raise ValueError("질문을 입력해 주세요.")

    agent = build_agent()

    # checkpointer 가 없어서 임시
    raw_result = agent.invoke(
           {"messages": [{"role": "user", "content": user_message}]},
           config={"configurable": {"thread_id": context.session_id}},
    )

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