"""StudySpot Streamlit 진입점.

담당: 역할 6 · 명하 · feature/ui
명세: docs/06_Streamlit_Integration.md

- 사용자 조건 입력, 대화형 결과, 후보 비교표, 근거·누락·Mock 표시, HITL 승인·거절 화면
- Agent 호출은 run_analysis(request, context) 경계를 통해서만 한다 (docs/00_공통계약.md 4절)
- UI는 State 전체를 전달·수정하지 않고, 점수를 재계산하지 않는다

현재 상태: 화면 뼈대. 역할 4의 `models/schemas.py`와 역할 5의 `agent.main_agent.run_analysis`가
없으면 `ui/contracts.py`의 임시 미러와 `ui/agent_client.py`의 stub으로 동작한다.
실제 모듈이 merge되면 코드 수정 없이 그쪽으로 전환된다.

실행: streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from ui import components
from ui import state as ui_state
from ui.agent_client import AGENT_CONNECTED, BACKEND, STUB_SCENARIOS, call_agent
from ui.contracts import SCHEMAS_SOURCE, USING_MIRROR, AgentRequest

st.set_page_config(page_title="StudySpot", page_icon="📚", layout="wide")

ui_state.init()


def _request_analysis(approval: dict | None = None) -> None:
    """호출 경계를 통과하는 유일한 함수. 여기 외에서 Agent를 호출하지 않는다."""
    request = AgentRequest(
        messages=list(ui_state.messages()),
        business_conditions=ui_state.conditions(),
        approval_decision=approval,
    )
    ui_state.set_busy(True)
    try:
        with st.spinner("분석 중입니다..."):
            response = call_agent(
                request,
                ui_state.context(),
                stub_scenario=st.session_state[ui_state.K_STUB_SCENARIO],
            )
    except Exception as exc:  # noqa: BLE001
        # TODO(역할 3): Guardrail 차단·반복 제한·타임아웃 예외 타입 확정 후 분기한다.
        # 앱을 중단시키지 않고 안내만 하며, 원문 응답·키를 화면에 노출하지 않는다(INT-09).
        ui_state.set_busy(False)
        st.error(f"요청을 처리하지 못했습니다. ({type(exc).__name__})")
        return
    ui_state.set_busy(False)

    ui_state.set_last_response(response)
    message = getattr(response, "message", "")
    if message:
        ui_state.append_message("assistant", message)


# --- 사이드바 ----------------------------------------------------------------

with st.sidebar:
    st.title("📚 StudySpot")
    st.caption("서울 내 지원 상권에서 스터디카페 출점 후보를 최대 3곳 추천합니다.")

    if not AGENT_CONNECTED or USING_MIRROR:
        st.warning(
            "개발 모드입니다. 아래 모듈이 아직 연결되지 않아 화면 확인용 값으로 동작합니다.\n\n"
            f"- 공통 모델: `{SCHEMAS_SOURCE}`\n"
            f"- Agent 진입점: `{BACKEND}`"
        )

    st.divider()
    st.subheader("분석 조건")
    submitted_conditions = components.render_conditions_form(ui_state.conditions())

    st.divider()
    if not AGENT_CONNECTED:
        st.selectbox(
            "stub 응답 시나리오",
            options=list(STUB_SCENARIOS),
            key=ui_state.K_STUB_SCENARIO,
            help="역할 5의 Agent 연결 전까지 상태별 화면을 확인하기 위한 개발용 선택입니다.",
        )

    if st.button("새 세션 시작", use_container_width=True, disabled=ui_state.is_busy()):
        ui_state.reset_session()
        st.rerun()

    context = ui_state.context()
    st.caption(f"session_id: `{context.session_id[:8]}…`")
    # user_id·user_role은 실행 계층이 주입한다. 화면에서 바꿀 수 없다.


# --- 본문 -------------------------------------------------------------------

st.header("출점 후보 분석")

if submitted_conditions is not None:
    ui_state.set_conditions(submitted_conditions)
    ui_state.append_message("user", "입력한 조건으로 분석을 요청합니다.")
    _request_analysis()

tab_result, tab_chat = st.tabs(["분석 결과", "대화 기록"])

with tab_result:
    decision = components.render_response(ui_state.last_response())
    if decision is not None:
        action, pending = decision
        key = ui_state.decision_key(pending.action_id, pending.payload_version, action)
        if ui_state.already_sent(key):
            # 중복 클릭·재실행 방어. 서버 측 중복 방지를 대체하지 않는다(INT-07).
            st.info("이미 전달한 요청입니다. 다시 전송하지 않았습니다.")
        else:
            ui_state.mark_sent(key)
            _request_analysis(
                approval={
                    "decision": action,
                    "action_id": pending.action_id,
                    "payload_version": pending.payload_version,
                }
            )
            st.rerun()

with tab_chat:
    history = ui_state.messages()
    if not history:
        st.caption("아직 대화가 없습니다.")
    for message in history:
        with st.chat_message(message.get("role", "assistant")):
            st.markdown(message.get("content", ""))

followup = st.chat_input(
    "조건을 바꾸거나 후속 질문을 입력하세요", disabled=ui_state.is_busy()
)
if followup:
    ui_state.append_message("user", followup)
    _request_analysis()
    st.rerun()
