"""SK 학원 수요 조회 Tool.

담당: 역할 1 · 중우 · feature/api-tools
명세: docs/01_API_Tool.md

- get_academy_demand(area, target_age, period) -> ToolResult
- 정상 data: AcademyDemandData 직렬화 사전
- 원천 누락은 None + missing_data. 학원 0개와 구분한다
- 재시도·Fallback 정책은 역할 3 소유. 여기서는 외부 요청 1회만 한다

현재 상태: 구조만 준비됨. 기능 미구현.
"""
