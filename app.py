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

import os
import threading
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# .env의 API 키를 프로세스 환경 변수로 올린다.
# agent/main_agent.py는 load_dotenv를 `if __name__ == "__main__"` 안에서만 부르기 때문에
# Streamlit이 run_analysis를 import해서 쓸 때는 실행되지 않는다. 환경 변수 주입은
# 실행 계층의 책임이므로 진입점인 app.py에서, ui 모듈을 import하기 전에 처리한다.
# override=True: 셸에 이미 OPENAI_API_KEY가 export돼 있으면 load_dotenv는 기본적으로
# .env 값을 무시한다. 저장소의 .env를 항상 기준으로 삼도록 덮어쓴다.
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from ui import components
from ui import state as ui_state
from ui.styles import apply_theme
from ui.agent_client import (
    AGENT_CONNECTED,
    BACKEND,
    STUB_SCENARIOS,
    build_favorite_message,
    call_agent,
)
from ui.contracts import SCHEMAS_SOURCE, USING_MIRROR, AgentRequest

st.set_page_config(page_title="StudySpot", page_icon="📚", layout="wide")
apply_theme()

# 키가 없으면 Agent 호출이 인증 오류로만 끝나 원인을 알기 어렵다.
# 값 자체는 절대 화면·로그에 출력하지 않고 설정 여부만 알린다 (docs/06 금지사항).
if AGENT_CONNECTED and not os.getenv("OPENAI_API_KEY"):
    st.error(
        "OPENAI_API_KEY가 설정되지 않았습니다. 저장소 루트의 `.env` 파일에 "
        "`OPENAI_API_KEY=...` 를 넣고 Streamlit을 재시작해 주세요. "
        "(`.env.example`이 아니라 `.env`입니다)"
    )
    st.stop()

ui_state.init()


#: 이 시간을 넘기면 화면에 원인 안내를 덧붙인다(초).
#: Agent 반복 제한(recursion_limit)이 확정되면 다시 조정한다.
SLOW_CALL_HINT_SECONDS = 90


def _call_with_progress(request: AgentRequest) -> object | None:
    """Agent 호출을 별도 스레드에서 돌리고 경과 시간을 1초마다 갱신한다.

    st.spinner는 호출이 끝날 때까지 화면이 멈춰 있어 진행 중인지 멎었는지 구분할 수
    없다. 실제 Agent는 Tool 호출을 여러 번 반복하느라 수 분이 걸릴 수 있어서,
    최소한 살아 있다는 것과 얼마나 지났는지는 보여 준다.

    스레드 안에서는 st.* 를 부르지 않으므로 Streamlit 실행 컨텍스트가 필요 없다.
    """
    context = ui_state.context()
    scenario = st.session_state[ui_state.K_STUB_SCENARIO]
    box: dict[str, object] = {}

    def worker() -> None:
        try:
            box["value"] = call_agent(request, context, stub_scenario=scenario)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True, name="studyspot-agent-call")
    thread.start()

    placeholder = st.empty()
    started = time.monotonic()
    while thread.is_alive():
        elapsed = int(time.monotonic() - started)
        text = f"분석 중입니다... ({elapsed}초 경과)"
        if elapsed >= SLOW_CALL_HINT_SECONDS:
            text += (
                "  \n오래 걸리고 있습니다. Agent가 Tool 호출을 반복하는 중일 수 있습니다. "
                "화면만 확인하려면 `.env`에 `STUDYSPOT_FORCE_STUB=1`을 넣고 재시작하세요."
            )
        placeholder.info(text)
        thread.join(timeout=1.0)
    placeholder.empty()

    error = box.get("error")
    if isinstance(error, Exception):
        raise error
    return box.get("value")


def _request_analysis(
    *,
    message: str | None = None,
    approval: dict | None = None,
    include_conditions: bool = True,
    cache_response: bool = True,
) -> object | None:
    """호출 경계를 통과하는 유일한 함수. 여기 외에서 Agent를 호출하지 않는다."""
    ui_state.set_busy(True)
    try:
        if approval is not None:
            request = AgentRequest(approval_decision=approval)
        else:
            request = AgentRequest(
                message=message,
                business_conditions=ui_state.conditions() if include_conditions else None,
            )
        response = _call_with_progress(request)
    except Exception as exc:  # noqa: BLE001
        # TODO(역할 3): Guardrail 차단·반복 제한·타임아웃 예외 타입 확정 후 분기한다.
        # 앱을 중단시키지 않고 안내만 하며, 원문 응답·키를 화면에 노출하지 않는다(INT-09).
        ui_state.set_busy(False)
        st.error(f"요청을 처리하지 못했습니다. ({type(exc).__name__})")
        return None
    ui_state.set_busy(False)

    if cache_response:
        ui_state.set_last_response(response)
    message = getattr(response, "message", "")
    if message:
        ui_state.append_message("assistant", message)
    return response


# --- 사이드바 ----------------------------------------------------------------

with st.sidebar:
    st.title("📚 StudySpot")
    st.caption("서울 상권 데이터를 바탕으로 스터디카페 출점 후보를 비교합니다.")

    if not AGENT_CONNECTED or USING_MIRROR:
        st.warning(
            "개발 모드입니다. 아래 모듈이 아직 연결되지 않아 화면 확인용 값으로 동작합니다.\n\n"
            f"- 공통 모델: `{SCHEMAS_SOURCE}`\n"
            f"- Agent 진입점: `{BACKEND}`"
        )

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

    st.divider()
    favorite_items = ui_state.favorites()
    favorite_title = "즐겨찾기" if AGENT_CONNECTED else "즐겨찾기 요청"
    st.subheader(f"★ {favorite_title} ({len(favorite_items)})")
    if not favorite_items:
        st.caption("아직 저장한 상권이 없습니다.")
    else:
        for favorite in favorite_items:
            st.markdown(f"**{favorite['area_name']}**")
            st.caption(f"commercial_area_id: `{favorite['commercial_area_id']}`")
    if not AGENT_CONNECTED:
        st.caption("Stub 모드에서는 현재 세션의 저장 요청만 표시하며, 실제 Store에는 저장되지 않습니다.")


# --- 본문 -------------------------------------------------------------------

st.markdown('<div class="studyspot-eyebrow">AI COMMERCIAL AREA ANALYSIS</div>', unsafe_allow_html=True)
st.title("출점 후보 분석")
st.markdown(
    '<div class="studyspot-subtitle">입력한 조건과 조회 가능한 데이터를 바탕으로 최대 3개 상권을 비교합니다.</div>',
    unsafe_allow_html=True,
)

if submitted_conditions is not None:
    ui_state.set_conditions(submitted_conditions)
    analysis_message = "입력한 조건으로 분석을 요청합니다."
    ui_state.append_message("user", analysis_message)
    _request_analysis(message=analysis_message)

tab_result, tab_chat = st.tabs(["분석 결과", "대화 기록"])

with tab_result:
    decision = components.render_response(ui_state.last_response())
    if decision is not None:
        action, pending = decision
        if action == "favorite":
            area_id = pending["commercial_area_id"]
            if ui_state.favorite_requested(area_id):
                st.info("이미 즐겨찾기 저장 요청을 전달했습니다.")
            else:
                favorite_message = build_favorite_message(area_id)
                ui_state.append_message("user", favorite_message)
                response = _request_analysis(
                    message=favorite_message,
                    include_conditions=False,
                    cache_response=False,
                )
                if response is not None:
                    ui_state.mark_favorite_requested(area_id, pending["area_name"])
                    st.rerun()
        else:
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
    _request_analysis(message=followup)
    st.rerun()
