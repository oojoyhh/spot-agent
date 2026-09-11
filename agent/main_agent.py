"""Agent 생성·Tool 등록·Memory/Middleware 연결.

담당: 역할 5 · 석휘 · feature/agent-core
명세: docs/05_Agent_Architecture.md

- 제안 진입점: run_analysis(request: AgentRequest, context: RuntimeContext) -> StudySpotResponse
- 실행 가능한 Tool만 등록한다. 미구현 Tool을 등록하지 않는다
- 모델 응답은 StudySpotResponse 검증 후 반환한다

현재 상태: 구조만 준비됨. 기능 미구현.
"""
# LangChain Agent 생성 함수
from langchain.agents import create_agent

# 프로젝트에서  작성된 시스템 프롬프트
from agent.prompts import SYSTEM_PROMPT

# Tool (임시)
from tools import academy_tools, action_tools, market_tools, scoring_tools, subway_tools

# Memory
from memory.state import state, store

# Middleware
from middleware import guardrails, middleware

# Schemas
from models import schemas

def run_analysis(request: AgentRequest, context: RuntimeContext):
        """분석 Agent 진입점. 실제 구현 전 임시 함수."""
        agent = create_agent(
                model="gpt-5-mini",
                tools=[],
                middleware=[],
                system_prompt=SYSTEM_PROMPT
        )

        