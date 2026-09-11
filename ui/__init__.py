"""StudySpot Streamlit UI 패키지.

담당: 역할 6 · 명하 · feature/ui
명세: docs/06_Streamlit_Integration.md

app.py는 진입점만 유지하고 화면 구성·상태·호출 경계는 이 패키지로 분리한다.
UI는 data/점수 Tool과 Store를 직접 호출하지 않으며, Agent 호출은
ui/agent_client.py의 run_analysis 경계 하나만 사용한다.
"""
