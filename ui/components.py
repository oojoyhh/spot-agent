"""상태별 화면 렌더링.

담당: 역할 6 · 명하 · feature/ui
명세: docs/06_Streamlit_Integration.md "상태별 화면 요구"

원칙
- 반환 모델(StudySpotResponse)의 필드로만 화면을 만든다.
- 추천 순서와 점수는 Agent 결과를 그대로 유지한다. UI에서 총점을 재계산하지 않는다.
- 세부 점수 None은 '데이터 없음 (총점에는 0점 반영)'으로 표시하고 0점으로 바꾸지 않는다.
- Mock은 근거와 추천 카드에 눈에 띄게 표시한다. 실/Mock 혼합 여부를 숨기지 않는다.
- confidence를 사업 성공 확률처럼 표현하지 않는다.
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from ui import state as ui_state
from ui.contracts import (
    APPROVAL_ACTION_LABELS,
    MISSING_SCORE_LABEL,
    PRIORITY_METRIC_OPTIONS,
    REQUIRED_FIELD_LABELS,
    SCORE_FIELDS,
    BusinessConditions,
)

# --- 조건 입력 폼 ---------------------------------------------------------------


def render_conditions_form(current: BusinessConditions) -> Optional[BusinessConditions]:
    """조건 입력 폼. 제출되면 새 BusinessConditions를, 아니면 None을 반환한다.

    기존 입력값은 재실행·후속 질문에서도 유지된다(INT-06).
    예산은 원(KRW) 단위이며 빈 값과 0을 구분한다.
    """
    with st.form("conditions_form"):
        st.caption("필수 조건: 희망 지역 · 보증금 · 월세 · 타깃 연령 · 운영 시작/종료 시간")

        region = st.text_input(
            "희망 지역",
            value=current.preferred_region or "",
            placeholder="예: 서울 노원구",
        )

        col1, col2 = st.columns(2)
        with col1:
            deposit_raw = st.text_input(
                "보증금 예산 (원)",
                value="" if current.deposit_budget is None else str(current.deposit_budget),
                placeholder="예: 50000000",
                help="비워 두면 '미입력'으로 전달합니다. 0을 넣으면 실제 0원으로 전달합니다.",
            )
        with col2:
            rent_raw = st.text_input(
                "월세 예산 (원)",
                value="" if current.monthly_rent_budget is None else str(current.monthly_rent_budget),
                placeholder="예: 3000000",
                help="비워 두면 '미입력'으로 전달합니다. 0을 넣으면 실제 0원으로 전달합니다.",
            )

        target_age = st.text_input(
            "타깃 연령",
            value=current.target_age or "",
            placeholder="예: 중고등학생, 20대 취업준비생",
        )

        col3, col4 = st.columns(2)
        with col3:
            start_raw = st.text_input(
                "운영 시작 시간 (HH:MM)",
                value=current.operating_start_time or "",
                placeholder="09:00",
            )
        with col4:
            end_raw = st.text_input(
                "운영 종료 시간 (HH:MM)",
                value=current.operating_end_time or "",
                placeholder="23:00",
                help="자정을 넘기는 영업시간도 입력할 수 있습니다.",
            )

        priorities = st.multiselect(
            "우선순위 지표 (참고용)",
            options=list(PRIORITY_METRIC_OPTIONS),
            default=[p for p in current.priority_metrics if p in PRIORITY_METRIC_OPTIONS],
            help="우선순위는 참고 정보입니다. 공통계약 5절에 따라 배점은 바뀌지 않습니다.",
        )

        submitted = st.form_submit_button(
            "분석 요청", type="primary", disabled=ui_state.is_busy()
        )

    if not submitted:
        return None

    errors: list[str] = []
    deposit, err = ui_state.parse_budget(deposit_raw)
    if err:
        errors.append(f"보증금 예산: {err}")
    rent, err = ui_state.parse_budget(rent_raw)
    if err:
        errors.append(f"월세 예산: {err}")
    start_time, err = ui_state.parse_time(start_raw)
    if err:
        errors.append(f"운영 시작 시간: {err}")
    end_time, err = ui_state.parse_time(end_raw)
    if err:
        errors.append(f"운영 종료 시간: {err}")

    if errors:
        for message in errors:
            st.error(message)
        return None

    return BusinessConditions(
        preferred_region=region.strip() or None,
        deposit_budget=deposit,
        monthly_rent_budget=rent,
        target_age=target_age.strip() or None,
        operating_start_time=start_time,
        operating_end_time=end_time,
        priority_metrics=priorities,
    )


# --- 공통 표시 도우미 -----------------------------------------------------------


def _has_mock_evidence(recommendation: Any) -> bool:
    return any(getattr(e, "is_mock", False) for e in getattr(recommendation, "evidence", []))


def _score_rows(recommendation: Any) -> list[dict[str, Any]]:
    rows = []
    for field, label, max_score in SCORE_FIELDS:
        value = getattr(recommendation, field, None)
        rows.append(
            {
                "항목": label,
                "점수": MISSING_SCORE_LABEL if value is None else f"{value:g} / {max_score}",
                "배점": max_score,
            }
        )
    return rows


def _render_score_consistency_note(recommendation: Any) -> None:
    """표시용 검증. 총점을 다시 계산해 화면 값으로 쓰지 않고 불일치만 알린다."""
    parts = [getattr(recommendation, f, None) for f, _, _ in SCORE_FIELDS]
    summed = sum(p for p in parts if p is not None)
    total = getattr(recommendation, "total_score", None)
    if total is not None and abs(summed - total) > 0.01:
        st.warning(
            f"세부 점수 합({summed:g})과 total_score({total:g})가 다릅니다. "
            "공통계약 5절 위반이므로 역할 4에게 전달해 주세요. "
            "화면은 Agent가 준 total_score를 그대로 표시합니다."
        )


def _render_confidence(value: Optional[float]) -> None:
    if value is None:
        st.caption("confidence: 제공되지 않음")
        return
    st.caption(
        f"confidence {value:g} — 데이터 충실도에 대한 내부 지표입니다. "
        "사업 성공 확률이 아닙니다."
    )


def _render_recommendation(index: int, recommendation: Any) -> None:
    name = getattr(recommendation, "area_name", "(이름 없음)")
    area_id = getattr(recommendation, "commercial_area_id", None)
    total = getattr(recommendation, "total_score", None)
    missing = list(getattr(recommendation, "missing_data", []) or [])

    header = f"{index}. {name}"
    if total is not None:
        header += f" — 총점 {total:g} / 100"
    st.markdown(f"### {header}")

    badges = []
    if _has_mock_evidence(recommendation):
        badges.append(":red-badge[Mock 데이터 포함]")
    if missing:
        badges.append(f":orange-badge[누락 지표 {len(missing)}건]")
    if area_id is None:
        badges.append(":gray-badge[상권 ID 없음]")
    if badges:
        st.markdown(" ".join(badges))

    st.dataframe(
        _score_rows(recommendation),
        hide_index=True,
        use_container_width=True,
        column_config={"배점": st.column_config.NumberColumn("배점", width="small")},
    )
    _render_score_consistency_note(recommendation)
    _render_confidence(getattr(recommendation, "confidence", None))

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**장점**")
        for item in getattr(recommendation, "strengths", []) or ["(없음)"]:
            st.markdown(f"- {item}")
    with col2:
        st.markdown("**위험요인**")
        for item in getattr(recommendation, "risks", []) or ["(없음)"]:
            st.markdown(f"- {item}")

    if missing:
        with st.expander(f"누락 데이터 {len(missing)}건", expanded=False):
            for item in missing:
                st.markdown(f"- {item}")
            st.caption(
                "누락 항목은 총점 계산에서 0점으로 처리됩니다. "
                "실제 관측된 0과 다릅니다."
            )

    evidence = list(getattr(recommendation, "evidence", []) or [])
    with st.expander(f"근거 · 출처 {len(evidence)}건", expanded=False):
        if not evidence:
            st.caption("제공된 근거가 없습니다.")
        for item in evidence:
            mark = " :red-badge[Mock]" if getattr(item, "is_mock", False) else ""
            st.markdown(f"- `{getattr(item, 'source', '?')}`{mark} — {getattr(item, 'summary', '')}")
        # CONTRACT-GAP: docs/06은 'Tool 호출 과정' 표시를 요구하지만 StudySpotResponse에는
        # tool_results가 없다(State는 UI로 전달되지 않음). 현재는 evidence로 대체하고,
        # 호출 추적이 필요하면 역할 4·5에게 계약 확장을 요청한다.

    st.divider()


def _render_comparison_table(recommendations: list[Any]) -> None:
    if len(recommendations) < 2:
        return
    rows = []
    for rec in recommendations:
        row: dict[str, Any] = {"상권": getattr(rec, "area_name", "?")}
        for field, label, _ in SCORE_FIELDS:
            value = getattr(rec, field, None)
            row[label] = "데이터 없음" if value is None else value
        row["총점"] = getattr(rec, "total_score", None)
        rows.append(row)
    with st.expander("후보 비교표", expanded=True):
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.caption("'데이터 없음'은 총점에 0점으로 반영된 항목입니다. 실제 0점과 다릅니다.")


# --- 상태별 화면 ---------------------------------------------------------------


def render_need_more_information(response: Any) -> None:
    st.warning(getattr(response, "message", "") or "추가 정보가 필요합니다.")
    missing = list(getattr(response, "missing_required_inputs", []) or [])
    if missing:
        st.markdown("**추가로 필요한 항목**")
        for field in missing:
            st.markdown(f"- {REQUIRED_FIELD_LABELS.get(field, field)}")
    st.info("왼쪽 입력값은 그대로 유지됩니다. 빠진 항목만 채우고 다시 요청해 주세요.")


def render_success(response: Any) -> None:
    recommendations = list(getattr(response, "recommendations", []) or [])
    message = getattr(response, "message", "")
    if message:
        st.markdown(message)

    if any(_has_mock_evidence(r) for r in recommendations):
        st.warning(
            "이 결과에는 Mock 데이터가 포함돼 있습니다. 실제 조회 결과와 섞여 있으니 "
            "각 후보의 근거에서 출처를 확인해 주세요."
        )

    st.caption(f"추천 {len(recommendations)}곳 (최대 3곳). 순서와 점수는 Agent 결과를 그대로 표시합니다.")
    _render_comparison_table(recommendations)
    for index, recommendation in enumerate(recommendations, start=1):
        _render_recommendation(index, recommendation)


def render_no_result(response: Any) -> None:
    message = getattr(response, "message", "") or "조건에 맞는 후보를 찾지 못했습니다."
    # 업무 결과(후보 0개)와 시스템 오류를 화면에서 구분한다(docs/06).
    looks_like_error = "error_code" in message or "오류" in message
    if looks_like_error:
        st.error(message)
        st.caption("분석이 완료된 결과가 아니라 처리 중 오류입니다. 잠시 후 다시 시도해 주세요.")
    else:
        st.info(message)
        st.caption("조건을 만족하는 후보가 없어 개수를 채우기 위한 추천은 만들지 않았습니다.")


def render_approval_required(response: Any) -> Optional[tuple[str, Any]]:
    """승인 화면. 사용자가 누르면 ("approve"|"reject", pending_action)을 반환한다.

    승인 전에는 실행 완료 표현을 쓰지 않는다. UI는 action_id를 만들어내지 않는다.
    """
    action_type = getattr(response, "approval_action", "none")
    st.subheader(f"승인 필요 — {APPROVAL_ACTION_LABELS.get(action_type, action_type)}")
    st.info("아직 실행되지 않았습니다. 아래 내용을 확인한 뒤 승인 또는 거절해 주세요.")

    message = getattr(response, "message", "")
    if message:
        st.markdown(message)

    pending = getattr(response, "pending_action", None)
    if pending is None:
        st.error(
            "승인에 필요한 action_id·payload_version이 응답에 없어 승인 요청을 보낼 수 없습니다. "
            "UI가 식별자를 임의로 만들지 않습니다. 역할 4·5에게 StudySpotResponse의 "
            "pending_action 필드 확정을 요청해 주세요."
        )
        return None

    st.code(getattr(pending, "display_summary", ""), language=None)
    st.caption(
        f"action_id: {getattr(pending, 'action_id', '?')} · "
        f"payload_version: {getattr(pending, 'payload_version', '?')}"
    )

    col1, col2 = st.columns(2)
    approve_key = ui_state.decision_key(
        getattr(pending, "action_id", ""), getattr(pending, "payload_version", ""), "approve"
    )
    reject_key = ui_state.decision_key(
        getattr(pending, "action_id", ""), getattr(pending, "payload_version", ""), "reject"
    )
    handled = ui_state.already_sent(approve_key) or ui_state.already_sent(reject_key)

    with col1:
        approved = st.button(
            "승인하고 실행 요청",
            type="primary",
            use_container_width=True,
            disabled=handled or ui_state.is_busy(),
            key=f"approve_{approve_key}",
        )
    with col2:
        rejected = st.button(
            "거절",
            use_container_width=True,
            disabled=handled or ui_state.is_busy(),
            key=f"reject_{reject_key}",
        )

    if handled:
        st.caption("이 요청은 이미 처리했습니다. 같은 내용은 다시 전송되지 않습니다.")
        return None
    if approved:
        return "approve", pending
    if rejected:
        return "reject", pending
    return None


def render_response(response: Any) -> Optional[tuple[str, Any]]:
    """status에 따라 화면을 그린다. 승인 화면에서만 사용자 결정을 반환한다."""
    if response is None:
        st.info("왼쪽에서 조건을 입력하고 분석을 요청해 주세요.")
        return None

    status = getattr(response, "status", None)
    if status == "need_more_information":
        render_need_more_information(response)
    elif status == "success":
        render_success(response)
    elif status == "no_result":
        render_no_result(response)
    elif status == "approval_required":
        return render_approval_required(response)
    else:
        st.error(f"처리할 수 없는 status입니다: {status!r}")
    return None
