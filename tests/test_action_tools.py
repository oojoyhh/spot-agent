import pytest

from models.schemas import ActionResult, ErrorCode, PendingAction
from tools.action_tools import create_site_visit_event, send_analysis_report


def _action(**overrides: object) -> PendingAction:
    values = {
        "action_id": "action-1",
        "action_type": "send_report",
        "payload_version": 1,
        "display_summary": "분석 보고서 반환",
        "status": "approved",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    values.update(overrides)
    return PendingAction(**values)


def test_send_analysis_report_returns_simulated_result() -> None:
    result = send_analysis_report(_action())

    assert result.success is True
    assert result.is_mock is True
    action_result = ActionResult.model_validate(result.data)
    assert action_result.action_id == "action-1"
    assert action_result.action_type == "send_report"
    assert action_result.status == "simulated"
    assert action_result.is_mock is True
    assert "실제 보고서는 전송되지 않았습니다" in action_result.message


@pytest.mark.parametrize(
    "action",
    [
        object(),
        _action(action_type="create_site_visit"),
        _action(status="pending"),
    ],
)
def test_send_analysis_report_rejects_invalid_or_unapproved_action(action: object) -> None:
    result = send_analysis_report(action)

    assert result.success is False
    assert result.error_code is ErrorCode.INVALID_INPUT
    assert result.is_mock is False


def test_create_site_visit_event_is_explicitly_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="MVP 구현 범위에서 제외"):
        create_site_visit_event(_action(action_type="create_site_visit"))
