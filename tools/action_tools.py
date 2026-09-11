"""보고서 반환 및 현장답사 일정 등록 Action Tool.

담당: 역할 1 · 중우 · feature/api-tools
명세: docs/00_공통계약.md, docs/01_API_Tool.md

두 Tool은 서버에서 검증된 사용자 승인 이후에만 실행한다.

현재 MVP 범위:
- ``send_analysis_report``는 외부 전송 없이 Streamlit에 표시할 Mock 실행
  결과만 반환한다.
- ``create_site_visit_event``는 구현하지 않으며 Agent에 등록하지 않는다.
"""

from __future__ import annotations

from models.schemas import ActionResult, ErrorCode, PendingAction, ToolResult

__all__ = ["create_site_visit_event", "send_analysis_report"]


_REPORT_SOURCE = "StudySpot Mock - analysis report"


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
    """MVP 구현 제외: 현장답사 일정 Tool은 Agent에 등록하지 않는다.

    ``pass``로 암묵적인 ``None``을 반환하면 공통 ToolResult 계약을 위반하므로,
    실수로 호출될 경우 명시적인 미구현 오류를 발생시킨다.
    """
    raise NotImplementedError("create_site_visit_event는 현재 MVP 구현 범위에서 제외되었습니다.")
