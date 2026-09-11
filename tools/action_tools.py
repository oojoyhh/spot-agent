"""보고서 반환 및 현장답사 일정 등록 Action Tool.

담당: 역할 1 · 중우 · feature/api-tools
명세: docs/00_공통계약.md, docs/01_API_Tool.md

두 Tool은 서버에서 검증된 사용자 승인 이후에만 실행한다.

현재 MVP 범위에서 두 Tool 모두 외부 서비스에 쓰지 않고 Streamlit에 표시할
``simulated`` Mock 결과만 반환한다.
"""

from __future__ import annotations

from models.schemas import ActionResult, ErrorCode, PendingAction, ToolResult

__all__ = ["create_site_visit_event", "send_analysis_report"]


_REPORT_SOURCE = "StudySpot Mock - analysis report"
_CALENDAR_SOURCE = "StudySpot Mock - site visit event"


def _failure(error_code: ErrorCode, message: str) -> ToolResult:
    return ToolResult(
        success=False,
        source=_REPORT_SOURCE,
        data={},
        error_code=error_code,
        error_message=message,
        is_mock=False,
    )


def send_analysis_report(approved_action: PendingAction) -> ToolResult:
    """승인된 보고서 action을 실제 전송 없이 Mock 결과로 반환한다.

    역할 5가 Agent Tool로 등록하고 역할 3 Middleware의 승인 검증을 통과한
    뒤 호출한다. 이 함수는 이메일이나 외부 서버에 데이터를 전송하지 않는다.
    """
    if not isinstance(approved_action, PendingAction):
        return _failure(ErrorCode.INVALID_INPUT, "승인된 서버 측 action이 필요합니다.")
    if approved_action.action_type != "send_report":
        return _failure(ErrorCode.INVALID_INPUT, "보고서 전송 action이 아닙니다.")
    if approved_action.status != "approved":
        return _failure(ErrorCode.INVALID_INPUT, "승인 완료된 action만 처리할 수 있습니다.")

    action_result = ActionResult(
        action_id=approved_action.action_id,
        action_type="send_report",
        status="simulated",
        message="Mock 실행: 실제 보고서는 전송되지 않았습니다.",
        is_mock=True,
    )
    return ToolResult(
        success=True,
        source=_REPORT_SOURCE,
        data=action_result.model_dump(mode="json"),
        error_code=None,
        error_message=None,
        is_mock=True,
    )


def create_site_visit_event(approved_action: PendingAction) -> ToolResult:
    """승인된 일정 action을 실제 등록 없이 Mock 결과로 반환한다."""
    if not isinstance(approved_action, PendingAction):
        return ToolResult(
            success=False,
            source=_CALENDAR_SOURCE,
            data={},
            error_code=ErrorCode.INVALID_INPUT,
            error_message="승인된 서버 측 action이 필요합니다.",
            is_mock=False,
        )
    if approved_action.action_type != "create_site_visit":
        return ToolResult(
            success=False,
            source=_CALENDAR_SOURCE,
            data={},
            error_code=ErrorCode.INVALID_INPUT,
            error_message="현장답사 일정 action이 아닙니다.",
            is_mock=False,
        )
    if approved_action.status != "approved":
        return ToolResult(
            success=False,
            source=_CALENDAR_SOURCE,
            data={},
            error_code=ErrorCode.INVALID_INPUT,
            error_message="승인 완료된 action만 처리할 수 있습니다.",
            is_mock=False,
        )

    action_result = ActionResult(
        action_id=approved_action.action_id,
        action_type="create_site_visit",
        status="simulated",
        message="Mock 실행: 실제 현장답사 일정은 등록되지 않았습니다.",
        is_mock=True,
    )
    return ToolResult(
        success=True,
        source=_CALENDAR_SOURCE,
        data=action_result.model_dump(mode="json"),
        error_code=None,
        error_message=None,
        is_mock=True,
    )
