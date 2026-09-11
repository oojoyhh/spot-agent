"""SK 지하철 역·출구 통행량 조회 Tool.

담당: 역할 1 · 중우 · feature/api-tools
명세: docs/01_API_Tool.md

- find_nearby_stations(latitude, longitude, radius_m) -> ToolResult (data: NearbyStation 목록)
- get_station_exit_traffic(station_id, period) -> ToolResult (data: StationTrafficData 사전)
- station_id는 인근 역 조회 결과의 코드 체계를 그대로 사용한다
- 출구별·시간대별 값의 중복 합산을 막도록 집계 단위를 문서화한다

현재 상태: 구조만 준비됨. 기능 미구현.
"""
