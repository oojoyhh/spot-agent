"""상권 검색·식별자·혼잡도·방문자·경쟁·임대료 조회 Tool.

담당: 인터페이스·통합은 역할 5 · 석휘 (추가 제안). 실제 구현 담당은 미정 (AG-09)
명세: docs/00_공통계약.md 2절, docs/05_Agent_Architecture.md ("미배정 Tool 계약 제안")

Tool 이름 (고정):
- search_supported_districts
- resolve_area_entities
- get_district_congestion
- get_visitor_demographics
- search_competitors
- get_rent_and_closure_data

모든 Tool은 ToolResult를 반환한다. 담당 확정 전에는 계약에 맞는 명시적 Mock(is_mock=True)으로 통합한다.

현재 상태: 구조만 준비됨. 기능 미구현.
"""
