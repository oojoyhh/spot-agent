"""입지점수 계산 Tool.

담당: 역할 4 · 효주 · feature/scoring
명세: docs/04_Scoring_Structured_Output.md

- calculate_market_score -> ToolResult (정상 data: MarketScore 직렬화 사전)
- 고정 배점: 학원 25 · 타깃 20 · 지하철 15 · 활성도 15 · 임대 15 · 경쟁 10
- total_score는 세부 점수 합과 일치한다. LLM이 점수를 만들지 않는다
- 누락 원천값을 0으로 대체하지 않는다. Mock 사용 시 is_mock=True를 전파한다
- 산식·정규화·confidence·반올림 정책은 docs/scoring.md에서 확정한다

현재 상태: 구조만 준비됨. 기능 미구현.
"""
