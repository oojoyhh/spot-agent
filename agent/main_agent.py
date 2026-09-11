"""Agent 생성·Tool 등록·Memory/Middleware 연결.

담당: 역할 5 · 석휘 · feature/agent-core
명세: docs/05_Agent_Architecture.md

- 제안 진입점: run_analysis(request: AgentRequest, context: RuntimeContext) -> StudySpotResponse
- 실행 가능한 Tool만 등록한다. 미구현 Tool을 등록하지 않는다
- 모델 응답은 StudySpotResponse 검증 후 반환한다

현재 상태: 구조만 준비됨. 기능 미구현.
"""
