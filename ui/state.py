"""UI 전용 세션 상태.

담당: 역할 6 · 명하 · feature/ui
명세: docs/06_Streamlit_Integration.md

session_state에는 **화면 입력·선택·승인 중복 방지 플래그만** 둔다.
분석 결과의 진실 원천은 역할 2·5의 State/Store이며 UI는 이를 이중 구현하지 않는다.
여기 보관하는 `last_response`는 마지막 응답을 다시 그리기 위한 화면 캐시일 뿐이고,
UI는 그 값을 편집하거나 점수를 재계산하지 않는다.

TODO(역할 2·5): 세션 유지·후속 질문 이어가기 방식 확정 후 session_id 발급 위치 재검토.
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, Optional

import streamlit as st

from ui.contracts import BusinessConditions, RuntimeContext

_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

# session_state 키를 한 곳에 모아 오타·중복 선언을 막는다.
K_MESSAGES = "ui_messages"            # 화면에 보여줄 대화 기록(입력 측)
K_CONDITIONS = "ui_conditions"        # 마지막으로 확정한 BusinessConditions
K_LAST_RESPONSE = "ui_last_response"  # 마지막 StudySpotResponse (표시 캐시)
K_SENT_DECISIONS = "ui_sent_decisions"  # 이미 전송한 승인 의도 키 집합
K_BUSY = "ui_busy"                    # 호출 중 버튼 잠금
K_CONTEXT = "ui_runtime_context"
K_STUB_SCENARIO = "ui_stub_scenario"
K_FAVORITE_REQUESTS = "ui_favorite_requests"
K_FAVORITES = "ui_favorites"

def init() -> None:
    """앱 최초 실행 시 한 번 세션 기본값을 만든다."""
    st.session_state.setdefault(K_MESSAGES, [])
    st.session_state.setdefault(K_CONDITIONS, BusinessConditions())
    st.session_state.setdefault(K_LAST_RESPONSE, None)
    st.session_state.setdefault(K_SENT_DECISIONS, set())
    st.session_state.setdefault(K_BUSY, False)
    st.session_state.setdefault(K_STUB_SCENARIO, "자동 (입력값에 따름)")
    st.session_state.setdefault(K_FAVORITE_REQUESTS, set())
    st.session_state.setdefault(K_FAVORITES, {})

    # 기존 세션에 ID만 저장된 항목도 목록에서 확인할 수 있게 옮긴다.
    for area_id in st.session_state[K_FAVORITE_REQUESTS]:
        st.session_state[K_FAVORITES].setdefault(area_id, area_id)
    if K_CONTEXT not in st.session_state:
        st.session_state[K_CONTEXT] = _build_runtime_context()


# --- RuntimeContext -------------------------------------------------------------


def _build_runtime_context() -> RuntimeContext:
    """실행 계층에서 주입한다. 사용자 입력으로 user_id·user_role을 바꾸지 않는다.

    TODO(역할 3·5): 실제 인증 연동 방식 확정. 현재는 로컬 실행용 기본값이며,
    배포 시 신뢰 가능한 인증 결과로 대체한다. 화면에 권한 선택 UI를 만들지 않는다.
    """
    return RuntimeContext(
        user_id=os.getenv("STUDYSPOT_USER_ID", "local-dev-user"),
        session_id=uuid.uuid4().hex,
        user_role=os.getenv("STUDYSPOT_USER_ROLE", "analyst"),
    )


def context() -> RuntimeContext:
    return st.session_state[K_CONTEXT]


def reset_session() -> None:
    """새 세션. 이전 사용자·세션 정보가 화면에 남지 않게 전부 비운다(INT-08)."""
    for key in (
        K_MESSAGES,
        K_CONDITIONS,
        K_LAST_RESPONSE,
        K_SENT_DECISIONS,
        K_BUSY,
        K_CONTEXT,
        K_FAVORITE_REQUESTS,
        K_FAVORITES,
    ):
        st.session_state.pop(key, None)
    init()


# --- 대화 --------------------------------------------------------------------


def messages() -> list[dict[str, str]]:
    return st.session_state[K_MESSAGES]


def append_message(role: str, content: str) -> None:
    st.session_state[K_MESSAGES].append({"role": role, "content": content})


# --- 조건 --------------------------------------------------------------------


def conditions() -> BusinessConditions:
    return st.session_state[K_CONDITIONS]


def set_conditions(value: BusinessConditions) -> None:
    """조건을 교체한다. 후속 질문에서도 기존 입력값은 화면에 유지된다(INT-06)."""
    st.session_state[K_CONDITIONS] = value

WON_PER_MANWON = 10_000

def parse_budget(raw: str) -> tuple[Optional[int], Optional[str]]:
    """예산 문자열 → 원(KRW) 정수.

    빈 값과 0을 구분한다. 빈 값은 (None, None), 0 입력은 (0, None)이다.
    """
    text = (raw or "").strip().replace(",", "").replace(" ", "")
    if text == "":
        return None, None
    if not text.isdigit():
        return None, "숫자만 입력해 주세요. 단위는 만원(KRW)입니다."
    return int(text) * WON_PER_MANWON, None

def format_budget(value: Optional[int]) -> str:
    if value is None:
        return ""
    return str(value // WON_PER_MANWON)

def parse_time(raw: str) -> tuple[Optional[str], Optional[str]]:
    """운영 시간 문자열 → "HH:MM". 빈 값은 (None, None)."""
    text = (raw or "").strip()
    if text == "":
        return None, None
    if not _TIME_RE.match(text):
        return None, "HH:MM 형식으로 입력해 주세요. (예: 09:00)"
    return text, None

def favorite_requested(commercial_area_id: str) -> bool:
    return commercial_area_id in st.session_state[K_FAVORITE_REQUESTS]


def mark_favorite_requested(commercial_area_id: str, area_name: str) -> None:
    st.session_state[K_FAVORITE_REQUESTS].add(commercial_area_id)
    st.session_state[K_FAVORITES][commercial_area_id] = area_name


def favorites() -> list[dict[str, str]]:
    """현재 UI 세션에서 저장 요청한 관심 상권을 반환한다."""
    return [
        {"commercial_area_id": area_id, "area_name": area_name}
        for area_id, area_name in st.session_state[K_FAVORITES].items()
    ]


# --- 응답 --------------------------------------------------------------------


def last_response() -> Any:
    return st.session_state[K_LAST_RESPONSE]

def set_last_response(response: Any) -> None:
    st.session_state[K_LAST_RESPONSE] = response


# --- 승인 중복 방지 -------------------------------------------------------------


def decision_key(action_id: str, payload_version: str, decision: str) -> str:
    return f"{action_id}|{payload_version}|{decision}"


def already_sent(key: str) -> bool:
    """버튼 중복 클릭·Streamlit 재실행으로 같은 의도가 재전송되는 것을 막는다(INT-07).

    UI 측 방어일 뿐이며 서버 측 중복 방지를 대체하지 않는다.
    """
    return key in st.session_state[K_SENT_DECISIONS]


def mark_sent(key: str) -> None:
    st.session_state[K_SENT_DECISIONS].add(key)


# --- 호출 중 잠금 ---------------------------------------------------------------


def is_busy() -> bool:
    return bool(st.session_state[K_BUSY])


def set_busy(value: bool) -> None:
    st.session_state[K_BUSY] = value
