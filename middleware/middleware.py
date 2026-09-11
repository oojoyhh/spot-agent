"""Middleware 실행 훅·재시도 연결.

담당: 역할 3 · 연주 · feature/guardrails
명세: docs/03_Guardrail_Middleware.md

- before_agent / before_model / wrap_tool_call / after_agent 훅 연결
- 외부 조회: 최초 1회 + 재시도 최대 2회, 중첩 재시도 금지
- 재시도 실패 시 캐시 또는 Mock으로 전환하고 사용자에게 표시
- 최대 Agent 반복 횟수 제한, 보고서 전송·일정 등록 전 HITL 승인

현재 상태: 구조만 준비됨. 기능 미구현.
"""
