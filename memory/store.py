"""장기 Memory (Store).

담당: 역할 2 · 소유 · feature/memory
명세: docs/02_Memory.md

- 세션을 넘어 유지할 사용자 선호만 저장: 예산, 타깃 고객, 선호 지역, 평가 우선순위, 관심 상권
- Tool 이름 (고정): save_user_preferences, save_shortlist
- user_id는 RuntimeContext에서 주입한다. 사용자 입력·LLM이 지정하지 않는다
- 선호 저장은 사용자의 명시적 요청·동의가 있을 때만 한다

현재 상태: 구조만 준비됨. 기능 미구현.
"""
