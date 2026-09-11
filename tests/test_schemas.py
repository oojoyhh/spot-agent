"""공통 모델 검증 테스트.

담당: 역할 4 · 효주
실행 (저장소 루트에서): python -m pytest tests/test_schemas.py
외부 호출 없음.
"""

import json
from datetime import date

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from models.schemas import (
    PENDING_ACTION_TRANSITIONS,
    SCORE_MAX_POINTS,
    AcademyDemandData,
    ActionResult,
    AgentRequest,
    AnalysisPeriod,
    ApprovalDecision,
    AreaIdentity,
    AreaRecommendation,
    BusinessConditions,
    ErrorCode,
    EvidenceItem,
    MarketScore,
    MetricObservation,
    NearbyStation,
    PendingAction,
    PendingActionView,
    RuntimeContext,
    ScoringInput,
    StationTrafficData,
    StudySpotResponse,
    StudySpotState,
    ToolResult,
    UserPreferences,
)


# ---------------------------------------------------------------------------
# 테스트용 입력
# ---------------------------------------------------------------------------


def period_kwargs(**overrides):
    base = {
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "day_types": ["weekday", "weekend"],
    }
    base.update(overrides)
    return base


def observation_kwargs(**overrides):
    base = {
        "metric_name": "academy_count",
        "value": 12.0,
        "unit": "개",
        "period": period_kwargs(),
        "source": "mock:test",
        "is_mock": True,
    }
    base.update(overrides)
    return base


def area_kwargs(**overrides):
    base = {
        "commercial_area_id": "3110001",
        "administrative_code": "1168010100",
        "area_name": "테스트 상권",
        "latitude": 37.5,
        "longitude": 127.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# SCH-01~06 ToolResult
# ---------------------------------------------------------------------------


def test_sch01_real_success():
    """SCH-01 실제 조회 성공: 오류 없음, is_mock=False."""
    result = ToolResult(success=True, source="sk_open_api", data={"k": 1}, is_mock=False)
    assert result.error_code is None


def test_sch02_failure_requires_error_code_and_empty_data():
    """SCH-02 실패는 error_code 필수, data는 빈 값."""
    ok = ToolResult(success=False, source="sk_open_api", data={}, error_code="NO_DATA", is_mock=False)
    assert ok.error_code == ErrorCode.NO_DATA
    assert ToolResult(success=False, source="s", data=[], error_code="API_TIMEOUT", is_mock=False).data == []

    with pytest.raises(ValidationError):
        ToolResult(success=False, source="s", data={}, is_mock=False)
    with pytest.raises(ValidationError):
        ToolResult(success=False, source="s", data={"k": 1}, error_code="NO_DATA", is_mock=False)
    with pytest.raises(ValidationError):
        ToolResult(success=False, source="s", data={}, error_code="NO_DATA", is_mock=True)


def test_sch03_mock_fallback_keeps_error_code():
    """SCH-03 API 실패 후 Mock: success=True, is_mock=True, 원래 오류 코드 유지."""
    result = ToolResult(
        success=True,
        source="mock:academy",
        data={"k": 1},
        error_code="API_TIMEOUT",
        error_message="SK API timeout, Mock으로 대체",
        is_mock=True,
    )
    assert result.is_mock and result.error_code == "API_TIMEOUT"

    with pytest.raises(ValidationError):
        ToolResult(success=True, source="s", data={}, error_code="API_TIMEOUT", is_mock=False)


def test_sch04_unknown_error_code_rejected():
    """SCH-04 공통 목록에 없는 오류 코드 거부."""
    with pytest.raises(ValidationError):
        ToolResult(success=False, source="s", data={}, error_code="UNSUPPORTED_REGION", is_mock=False)


def test_sch05_error_message_requires_code():
    """SCH-05 error_message만 있고 error_code가 없으면 거부."""
    with pytest.raises(ValidationError):
        ToolResult(success=True, source="s", data={}, error_message="설명", is_mock=False)


def test_sch06_extra_field_rejected():
    """SCH-06 선언되지 않은 필드 거부 (오타 방지)."""
    with pytest.raises(ValidationError):
        ToolResult(success=True, source="s", data={}, is_mock=False, metadata={})
    with pytest.raises(ValidationError):
        AreaIdentity(**area_kwargs(area_nmae="오타"))


# ---------------------------------------------------------------------------
# SCH-07~08 식별자
# ---------------------------------------------------------------------------


def test_sch07_codes_are_strings_with_leading_zero():
    """SCH-07 코드는 문자열로 앞자리 0 보존, 숫자 입력은 거부."""
    area = AreaIdentity(**area_kwargs(commercial_area_id="0123"))
    assert area.commercial_area_id == "0123"
    assert NearbyStation(
        station_id="0222", station_name="역", latitude=37.5, longitude=127.0, distance_m=0
    ).station_id == "0222"

    with pytest.raises(ValidationError):
        AreaIdentity(**area_kwargs(commercial_area_id=123))
    with pytest.raises(ValidationError):
        AreaIdentity(**area_kwargs(commercial_area_id="   "))


def test_sch08_area_unknown_values_and_coordinates():
    """SCH-08 모르는 코드·좌표는 None 허용, 좌표는 쌍으로만, 범위 검사."""
    area = AreaIdentity(**area_kwargs(administrative_code=None, latitude=None, longitude=None))
    assert area.administrative_code is None

    with pytest.raises(ValidationError):
        AreaIdentity(**area_kwargs(longitude=None))
    with pytest.raises(ValidationError):
        AreaIdentity(**area_kwargs(latitude=91))
    with pytest.raises(ValidationError):
        NearbyStation(station_id="1", station_name="역", latitude=37.5, longitude=127.0, distance_m=-1)


# ---------------------------------------------------------------------------
# SCH-09 기간
# ---------------------------------------------------------------------------


def test_sch09_analysis_period_rules():
    """SCH-09 날짜 순서, HH:MM 형식, 시각 쌍, 자정 통과, day_types."""
    period = AnalysisPeriod(**period_kwargs())
    assert period.start_date == date(2026, 8, 1)
    assert period.timezone == "Asia/Seoul"
    assert AnalysisPeriod(**period_kwargs(start_time="22:00", end_time="02:00")).end_time == "02:00"

    invalid_cases = [
        period_kwargs(end_date="2026-07-31"),
        period_kwargs(start_time="9:00", end_time="18:00"),
        period_kwargs(start_time="24:00", end_time="18:00"),
        period_kwargs(start_time="09:00"),
        period_kwargs(start_time="09:00", end_time="09:00"),
        period_kwargs(day_types=[]),
        period_kwargs(day_types=["weekday", "weekday"]),
        period_kwargs(day_types=["monday"]),
    ]
    for kwargs in invalid_cases:
        with pytest.raises(ValidationError):
            AnalysisPeriod(**kwargs)


# ---------------------------------------------------------------------------
# SCH-10 관측값: 실제 0과 누락 구분
# ---------------------------------------------------------------------------


def test_sch10_zero_and_missing_are_distinct():
    """SCH-10 실제 0은 value=0.0, 누락은 None + missing_reason."""
    zero = MetricObservation(**observation_kwargs(value=0))
    assert zero.value == 0.0 and zero.missing_reason is None

    missing = MetricObservation(**observation_kwargs(value=None, missing_reason="API 미지원 지표"))
    assert missing.value is None

    with pytest.raises(ValidationError):
        MetricObservation(**observation_kwargs(value=None))
    with pytest.raises(ValidationError):
        MetricObservation(**observation_kwargs(value=3.0, missing_reason="모순"))
    with pytest.raises(ValidationError):
        MetricObservation(**observation_kwargs(value=float("nan")))
    with pytest.raises(ValidationError):
        MetricObservation(**{k: v for k, v in observation_kwargs().items() if k != "value"})


# ---------------------------------------------------------------------------
# SCH-11~13 직렬화·기본값
# ---------------------------------------------------------------------------


def test_sch11_serialization_roundtrip_preserves_none():
    """SCH-11 JSON 직렬화 후 복원: 필드·값·None 보존."""
    payload = AcademyDemandData(
        commercial_area_id="0123",
        administrative_code=None,
        observations=[
            MetricObservation(**observation_kwargs()),
            MetricObservation(**observation_kwargs(metric_name="student_count", value=None, missing_reason="미제공")),
        ],
        missing_data=["student_count"],
    )
    dumped = payload.model_dump(mode="json")
    assert dumped["observations"][0]["period"]["start_date"] == "2026-08-01"

    restored = AcademyDemandData.model_validate(json.loads(json.dumps(dumped)))
    assert restored == payload
    assert restored.administrative_code is None
    assert restored.observations[1].value is None


def test_sch12_tool_result_carries_serialized_payload():
    """SCH-12 ToolResult.data에 직렬화한 payload를 담고 다시 모델로 복원."""
    traffic = StationTrafficData(
        station_id="0222",
        observations=[
            MetricObservation(
                **observation_kwargs(
                    metric_name="exit_traffic",
                    value=1500,
                    unit="명/일",
                    dimensions={"exit_number": "3", "day_type": "weekday", "time_slot": "18:00-22:00"},
                )
            )
        ],
    )
    result = ToolResult(success=True, source="mock:subway", data=traffic.model_dump(mode="json"), is_mock=True)
    restored = StationTrafficData.model_validate(ToolResult.model_validate_json(result.model_dump_json()).data)
    assert restored == traffic

    stations = [NearbyStation(station_id="0222", station_name="역", latitude=37.5, longitude=127.0, distance_m=320.5)]
    listed = ToolResult(success=True, source="mock:subway", data=[s.model_dump(mode="json") for s in stations], is_mock=True)
    assert NearbyStation.model_validate(listed.data[0]) == stations[0]


def test_sch13_default_lists_are_independent():
    """SCH-13 목록·사전 기본값은 인스턴스마다 독립."""
    first = StationTrafficData(station_id="1", observations=[MetricObservation(**observation_kwargs())])
    second = StationTrafficData(station_id="2", observations=[MetricObservation(**observation_kwargs())])
    first.missing_data.append("exit_traffic")
    assert second.missing_data == []

    obs_a = MetricObservation(**observation_kwargs())
    obs_b = MetricObservation(**observation_kwargs())
    obs_a.dimensions["exit_number"] = "1"
    assert obs_b.dimensions == {}


# ---------------------------------------------------------------------------
# SCH-14 dimensions key 통일
# ---------------------------------------------------------------------------


def test_sch14_dimension_keys_are_standardized():
    """SCH-14 dimensions는 등록된 key만 허용, 값 형식·기간 일관성 검사."""
    obs = MetricObservation(
        **observation_kwargs(
            metric_name="exit_traffic",
            value=1500,
            unit="명/일",
            dimensions={"exit_number": "3", "day_type": "weekday", "time_slot": "22:00-02:00"},
        )
    )
    assert obs.dimensions["time_slot"] == "22:00-02:00"

    invalid_dimensions = [
        {"exit": "3"},  # 등록되지 않은 key
        {"day_type": "holiday"},  # period.day_types에 없음
        {"day_type": "monday"},
        {"time_slot": "18-22"},  # 형식 오류
        {"time_slot": "18:00-18:00"},  # 시작=종료
        {"exit_number": " "},  # 빈 값
    ]
    for dims in invalid_dimensions:
        with pytest.raises(ValidationError):
            MetricObservation(**observation_kwargs(dimensions=dims))


# ===========================================================================
# 2차 선언: 입력·점수·응답·승인·State
# ===========================================================================


def score_kwargs(**overrides):
    """손으로 계산한 기준 예제: 20 + 15 + 12.5 + 10 + 15 + 5 = 77.5"""
    base = {
        "academy_demand_score": 20.0,
        "target_customer_score": 15.0,
        "station_traffic_score": 12.5,
        "activity_score": 10.0,
        "rent_score": 15.0,
        "competition_score": 5.0,
        "total_score": 77.5,
        "confidence": 0.8,
    }
    base.update(overrides)
    return base


def recommendation_kwargs(**overrides):
    base = score_kwargs(
        commercial_area_id="3110001",
        area_name="테스트 상권",
        strengths=["학원 밀집"],
        evidence=[{"source": "mock:academy", "summary": "반경 내 학원 12개", "is_mock": True}],
    )
    base.update(overrides)
    return base


def pending_action_kwargs(**overrides):
    base = {
        "action_id": "act-1",
        "action_type": "send_report",
        "payload_version": 1,
        "display_summary": "분석 보고서를 이메일로 전송",
        "user_id": "u1",
        "session_id": "s1",
    }
    base.update(overrides)
    return base


def full_conditions(**overrides):
    base = {
        "preferred_region": "강남",
        "deposit_budget": 30_000_000,
        "monthly_rent_budget": 2_000_000,
        "target_age": "20대",
        "operating_start_time": "09:00",
        "operating_end_time": "02:00",
    }
    base.update(overrides)
    return BusinessConditions(**base)


# ---------------------------------------------------------------------------
# SCH-15~17 입력·신원·선호
# ---------------------------------------------------------------------------


def test_sch15_business_conditions():
    """SCH-15 부분 입력 허용, 필수 조건 누락 목록, 예산·시간·우선순위 검증."""
    assert BusinessConditions().missing_required_inputs() == [
        "preferred_region",
        "deposit_budget",
        "monthly_rent_budget",
        "target_age",
        "operating_start_time",
        "operating_end_time",
    ]
    partial = BusinessConditions(preferred_region="강남", deposit_budget=30_000_000, monthly_rent_budget=2_000_000)
    assert partial.missing_required_inputs() == ["target_age", "operating_start_time", "operating_end_time"]

    full_24h = BusinessConditions(
        preferred_region="강남",
        deposit_budget=0,
        monthly_rent_budget=2_000_000,
        target_age="20대",
        operating_start_time="00:00",
        operating_end_time="00:00",
        priority_metrics=["rent_score", "academy_demand_score"],
    )
    assert full_24h.missing_required_inputs() == []
    assert BusinessConditions(operating_start_time="09:00", operating_end_time="02:00").operating_end_time == "02:00"

    invalid_cases = [
        {"deposit_budget": -1},
        {"deposit_budget": "삼천만"},
        {"operating_start_time": "9:00"},
        {"priority_metrics": ["price"]},
        {"priority_metrics": ["rent_score", "rent_score"]},
    ]
    for kwargs in invalid_cases:
        with pytest.raises(ValidationError):
            BusinessConditions(**kwargs)


def test_sch16_runtime_context_is_frozen():
    """SCH-16 RuntimeContext는 생성 후 변경 불가, 빈 값 거부."""
    context = RuntimeContext(user_id="u1", session_id="s1", user_role="user")
    with pytest.raises(ValidationError):
        context.user_id = "someone-else"
    with pytest.raises(ValidationError):
        RuntimeContext(user_id=" ", session_id="s1", user_role="user")


def test_sch17_user_preferences():
    """SCH-17 target_age로 통일 (target_customer 거부), 중복·기본값 독립."""
    prefs = UserPreferences(user_id="u1", target_age="20대", shortlisted_areas=["0123"])
    assert prefs.shortlisted_areas == ["0123"]
    assert UserPreferences(user_id="u2").preferred_regions == []

    with pytest.raises(ValidationError):
        UserPreferences(user_id="u1", target_customer="20대")
    with pytest.raises(ValidationError):
        UserPreferences(user_id="u1", shortlisted_areas=["0123", "0123"])


# ---------------------------------------------------------------------------
# SCH-18~19 점수·추천
# ---------------------------------------------------------------------------


def test_sch18_market_score_invariants():
    """SCH-18 배점 범위, 총점 = 세부 점수 합(None=0), 총점 변조 거부, confidence 0~1."""
    assert sum(SCORE_MAX_POINTS.values()) == 100
    assert MarketScore(**score_kwargs()).total_score == 77.5

    # 실제 0: 누락 사유 없이 허용 (77.5 - 15 = 62.5)
    assert MarketScore(**score_kwargs(rent_score=0.0, total_score=62.5)).rent_score == 0.0
    # 일부 누락: None은 0점 (77.5 - 12.5 = 65.0)
    partial = MarketScore(
        **score_kwargs(station_traffic_score=None, total_score=65.0, missing_data=["station_traffic: 역 데이터 없음"])
    )
    assert partial.station_traffic_score is None
    # 전 항목 누락도 MarketScore로는 표현 가능 (추천에서는 제외)
    names = list(SCORE_MAX_POINTS)
    all_missing = MarketScore(
        **score_kwargs(**{n: None for n in names}, total_score=0.0, confidence=0.0, missing_data=["전 항목 없음"])
    )
    assert all_missing.total_score == 0.0
    # 부동소수 합 오차 허용 (0.1 + 0.2)
    tiny = {n: 0.0 for n in names} | {"academy_demand_score": 0.1, "rent_score": 0.2}
    assert MarketScore(**score_kwargs(**tiny, total_score=0.3)).total_score == 0.3

    invalid_cases = [
        score_kwargs(total_score=80.0),  # 총점 변조
        score_kwargs(academy_demand_score=25.5, total_score=83.0),  # 배점 초과
        score_kwargs(rent_score=-1.0, total_score=61.5),  # 음수
        score_kwargs(confidence=1.2),
        score_kwargs(station_traffic_score=None, total_score=65.0),  # 누락 사유 없음
    ]
    for kwargs in invalid_cases:
        with pytest.raises(ValidationError):
            MarketScore(**kwargs)


def test_sch19_area_recommendation():
    """SCH-19 전 항목 누락 추천 불가, 일부 누락은 risks 필수, 근거 1개 이상."""
    rec = AreaRecommendation(**recommendation_kwargs())
    assert rec.commercial_area_id == "3110001"
    assert isinstance(rec.evidence[0], EvidenceItem)

    partial_ok = recommendation_kwargs(rent_score=None, total_score=62.5, missing_data=["rent: 없음"], risks=["임대료 비교 한계"])
    assert AreaRecommendation(**partial_ok).rent_score is None

    names = list(SCORE_MAX_POINTS)
    invalid_cases = [
        recommendation_kwargs(**{n: None for n in names}, total_score=0.0, missing_data=["없음"], risks=["없음"]),
        recommendation_kwargs(rent_score=None, total_score=62.5, missing_data=["rent: 없음"]),  # risks 없음
        recommendation_kwargs(evidence=[]),
    ]
    for kwargs in invalid_cases:
        with pytest.raises(ValidationError):
            AreaRecommendation(**kwargs)


# ---------------------------------------------------------------------------
# SCH-20~21 행동 결과·최종 응답
# ---------------------------------------------------------------------------


def test_sch20_action_result_mock_is_not_executed():
    """SCH-20 Mock은 executed로 표시할 수 없고, simulated는 Mock일 때만."""
    base = {"action_id": "act-1", "action_type": "send_report", "message": "전송 결과"}
    assert ActionResult(**base, status="executed", is_mock=False).status == "executed"
    assert ActionResult(**base, status="simulated", is_mock=True).is_mock
    assert ActionResult(**base, status="rejected", is_mock=True).status == "rejected"

    with pytest.raises(ValidationError):
        ActionResult(**base, status="executed", is_mock=True)
    with pytest.raises(ValidationError):
        ActionResult(**base, status="simulated", is_mock=False)


def test_sch21_response_status_combinations():
    """SCH-21 status별 추천 개수·누락 입력·승인 조합 검증."""
    rec = AreaRecommendation(**recommendation_kwargs())
    other = [AreaRecommendation(**recommendation_kwargs(commercial_area_id=str(i))) for i in range(4)]
    action = ActionResult(action_id="act-1", action_type="send_report", status="simulated", message="Mock 전송", is_mock=True)
    executed = ActionResult(action_id="act-1", action_type="send_report", status="executed", message="전송 완료", is_mock=False)
    view = PendingAction(**pending_action_kwargs()).to_view()

    valid_cases = [
        {"status": "success", "recommendations": [rec], "message": "추천 1곳"},
        {"status": "success", "recommendations": other[:3], "message": "추천 3곳"},
        {"status": "success", "message": "보고서 전송 시연", "action_result": action},
        {"status": "need_more_information", "message": "연령을 알려주세요", "missing_required_inputs": ["target_age"]},
        {"status": "no_result", "message": "조건에 맞는 상권 없음"},
        {
            "status": "approval_required",
            "recommendations": [rec],
            "message": "보고서를 보낼까요?",
            "requires_approval": True,
            "approval_action": "send_report",
            "pending_action": view,
        },
    ]
    for kwargs in valid_cases:
        StudySpotResponse(**kwargs)

    invalid_cases = [
        {"status": "success", "message": "추천 없음"},  # 추천·행동 결과 모두 없음
        {"status": "success", "recommendations": other, "message": "4곳"},  # 3개 초과
        {"status": "success", "recommendations": [rec, rec], "message": "중복"},
        {"status": "need_more_information", "message": "질문"},  # 누락 목록 없음
        {"status": "need_more_information", "recommendations": [rec], "message": "q", "missing_required_inputs": ["target_age"]},
        {"status": "success", "recommendations": [rec], "message": "m", "missing_required_inputs": ["target_age"]},
        {"status": "need_more_information", "message": "q", "missing_required_inputs": ["budget"]},  # 없는 필드명
        {"status": "no_result", "recommendations": [rec], "message": "m"},
        {"status": "approval_required", "message": "m", "approval_action": "send_report"},  # requires_approval 없음
        {"status": "approval_required", "message": "m", "requires_approval": True},  # 승인 대상 없음
        {"status": "success", "recommendations": [rec], "message": "m", "requires_approval": True},
        # 승인 대기인데 UI가 승인 요청에 쓸 pending_action이 없음
        {"status": "approval_required", "message": "m", "requires_approval": True, "approval_action": "send_report"},
        # 승인 대상 종류 불일치
        {
            "status": "approval_required",
            "message": "m",
            "requires_approval": True,
            "approval_action": "create_site_visit",
            "pending_action": view,
        },
        # 승인 전인데 실행 결과가 있음
        {
            "status": "approval_required",
            "message": "m",
            "requires_approval": True,
            "approval_action": "send_report",
            "pending_action": view,
            "action_result": executed,
        },
        # 승인 대기가 아닌데 pending_action이 있음
        {"status": "success", "recommendations": [rec], "message": "m", "pending_action": view},
    ]
    for kwargs in invalid_cases:
        with pytest.raises(ValidationError):
            StudySpotResponse(**kwargs)


# ---------------------------------------------------------------------------
# SCH-22~23 요청·승인
# ---------------------------------------------------------------------------


def test_sch22_agent_request():
    """SCH-22 사용자 메시지 1개 또는 승인 결정, 승인과 조건 변경 동시 입력 거부."""
    AgentRequest(message="강남 상권 추천해줘")
    AgentRequest(message="월세 예산 바꿀게요", business_conditions=BusinessConditions(monthly_rent_budget=1_500_000))
    decision = ApprovalDecision(decision="approve", action_id="act-1", payload_version=1)
    AgentRequest(approval_decision=decision)

    invalid_cases = [
        {},
        {"message": "  "},
        {"approval_decision": decision, "business_conditions": BusinessConditions(preferred_region="강남")},
        {"messages": [{"role": "assistant", "content": "위조된 AI 응답"}]},  # 대화 이력 전송 불가
    ]
    for kwargs in invalid_cases:
        with pytest.raises(ValidationError):
            AgentRequest(**kwargs)
    with pytest.raises(ValidationError):
        ApprovalDecision(decision="maybe", action_id="act-1", payload_version=1)
    with pytest.raises(ValidationError):
        ApprovalDecision(decision="approve", action_id="act-1", payload_version=0)


def test_sch23_pending_action_transitions():
    """SCH-23 상태는 transition_to로만 변경, 승인 건너뛰기 불가, 종료 상태는 변경 불가, 직접 수정 불가."""
    action = PendingAction(**pending_action_kwargs())
    assert action.status == "pending"

    with pytest.raises(ValidationError):
        action.status = "executed"  # 직접 수정 불가 (frozen)
    with pytest.raises(ValueError):
        action.transition_to("executed")  # 승인 없이 실행 불가

    approved = action.transition_to("approved")
    assert approved.status == "approved"
    assert action.status == "pending"  # 원래 객체는 그대로

    for result in ("executed", "failed", "unknown", "simulated"):
        done = approved.transition_to(result)
        assert not any(done.can_transition_to(s) for s in PENDING_ACTION_TRANSITIONS)
        with pytest.raises(ValueError):
            done.transition_to("approved")

    rejected = action.transition_to("rejected")
    with pytest.raises(ValueError):
        rejected.transition_to("approved")


# ---------------------------------------------------------------------------
# SCH-24~25 직렬화
# ---------------------------------------------------------------------------


def test_sch24_scoring_input_roundtrip():
    """SCH-24 ScoringInput은 ToolResult 사전을 담고 JSON 복원 가능."""
    scoring_input = ScoringInput(
        area=area_kwargs(),
        conditions=full_conditions(),
        period=period_kwargs(),
        tool_results={
            "get_academy_demand": ToolResult(success=True, source="mock:academy", data={"k": 1}, is_mock=True),
            "search_competitors": ToolResult(success=False, source="mock", data=[], error_code="NO_DATA", is_mock=False),
        },
    )
    assert ScoringInput.model_validate_json(scoring_input.model_dump_json()) == scoring_input


def test_sch25_response_roundtrip_preserves_none():
    """SCH-25 최종 응답 직렬화 후 복원: None 점수·근거 Mock 여부 보존."""
    rec = AreaRecommendation(
        **recommendation_kwargs(rent_score=None, total_score=62.5, missing_data=["rent: 없음"], risks=["임대료 비교 한계"])
    )
    response = StudySpotResponse(status="success", recommendations=[rec], message="추천 1곳")
    restored = StudySpotResponse.model_validate_json(response.model_dump_json())
    assert restored == response
    assert restored.recommendations[0].rent_score is None
    assert restored.recommendations[0].evidence[0].is_mock is True


# ---------------------------------------------------------------------------
# SCH-26 LangChain create_agent 호환
# ---------------------------------------------------------------------------


def test_sch26_state_schema_works_with_create_agent(caplog):
    """SCH-26 StudySpotState·RuntimeContext가 create_agent와 checkpointer에서 동작 (가짜 모델, 외부 호출 없음)."""
    import logging
    import warnings

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from models.schemas import STATE_CHECKPOINT_TYPES

    model = GenericFakeChatModel(messages=iter([AIMessage(content="첫 응답"), AIMessage(content="두 번째 응답")]))
    saver = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_CHECKPOINT_TYPES))
    agent = create_agent(
        model=model, tools=[], state_schema=StudySpotState, context_schema=RuntimeContext, checkpointer=saver
    )
    config = {"configurable": {"thread_id": "thread-1"}}
    context = RuntimeContext(user_id="u1", session_id="s1", user_role="user")

    conditions = BusinessConditions(preferred_region="강남")
    area = AreaIdentity(**area_kwargs())
    failed = ToolResult(success=False, source="sk_open_api", data={}, error_code="API_TIMEOUT", is_mock=False)
    score = MarketScore(**score_kwargs())
    pending = PendingAction(**pending_action_kwargs())

    with warnings.catch_warnings(record=True) as caught, caplog.at_level(logging.WARNING):
        warnings.simplefilter("always")
        agent.invoke(
            {
                "messages": [HumanMessage("강남 상권 추천해줘")],
                "business_conditions": conditions,
                "current_candidates": [area],
                "tool_results": {"call-1": failed},
                "market_scores": {"3110001": score},
                "pending_action": pending,
            },
            context=context,
            config=config,
        )
        state = agent.invoke({"messages": [HumanMessage("다시 보여줘")]}, context=context, config=config)

    assert state["business_conditions"] == conditions
    assert state["current_candidates"] == [area]
    assert state["tool_results"]["call-1"].error_code == ErrorCode.API_TIMEOUT
    assert state["market_scores"]["3110001"] == score
    assert state["pending_action"] == pending
    assert len(state["messages"]) == 4

    logged = caplog.text + " ".join(str(w.message) for w in caught)
    assert "unregistered" not in logged


# ---------------------------------------------------------------------------
# SCH-27~31 리뷰 반영 보완
# ---------------------------------------------------------------------------


def test_sch27_pending_action_view_for_ui():
    """SCH-27 승인 화면용 공개 정보에는 user_id·session_id가 없고, 승인 요청에 그대로 쓸 수 있다."""
    view = PendingAction(**pending_action_kwargs()).to_view()
    assert isinstance(view, PendingActionView)
    assert view.model_dump() == {
        "action_id": "act-1",
        "action_type": "send_report",
        "payload_version": 1,
        "display_summary": "분석 보고서를 이메일로 전송",
    }
    decision = ApprovalDecision(decision="approve", action_id=view.action_id, payload_version=view.payload_version)
    assert (decision.action_id, decision.payload_version) == ("act-1", 1)


def test_sch28_scoring_input_requires_complete_conditions():
    """SCH-28 필수 조건이 빠진 상태로는 점수 입력을 만들 수 없다."""
    with pytest.raises(ValidationError):
        ScoringInput(area=area_kwargs(), conditions=BusinessConditions(preferred_region="강남"), period=period_kwargs())
    with pytest.raises(ValidationError):
        ScoringInput(area=area_kwargs(), conditions=full_conditions(target_age=None), period=period_kwargs())


def test_sch29_numeric_evidence_is_traceable():
    """SCH-29 수치 근거는 Tool·지표·단위와 함께, 정성 근거는 설명만으로 허용."""
    EvidenceItem(source="서울시 상권분석", summary="2026-08 기준 조사 자료", is_mock=False)
    numeric = EvidenceItem(
        source="mock:academy",
        summary="반경 내 학원 12개",
        is_mock=True,
        tool_name="get_academy_demand",
        metric_name="academy_count",
        value=12,
        unit="개",
    )
    assert numeric.value == 12.0

    with pytest.raises(ValidationError):
        EvidenceItem(source="공공데이터", summary="방문자 999만 명", is_mock=False, value=9_990_000)
    with pytest.raises(ValidationError):
        EvidenceItem(
            source="s", summary="s", is_mock=False, tool_name="t", metric_name="m", value=float("inf"), unit="명"
        )


def test_sch30_all_missing_score_has_zero_confidence():
    """SCH-30 전 항목 누락이면 confidence는 0."""
    none_scores = {n: None for n in SCORE_MAX_POINTS}
    with pytest.raises(ValidationError):
        MarketScore(**score_kwargs(**none_scores, total_score=0.0, confidence=0.5, missing_data=["전 항목 없음"]))


def test_sch31_data_payload_cannot_be_empty():
    """SCH-31 학원·지하철 데이터는 관측값 또는 누락 사유 중 하나 이상 필요 (학원 0개는 value=0 관측값)."""
    with pytest.raises(ValidationError):
        AcademyDemandData(commercial_area_id="3110001", administrative_code=None)
    with pytest.raises(ValidationError):
        StationTrafficData(station_id="0222")

    zero = AcademyDemandData(
        commercial_area_id="3110001",
        administrative_code=None,
        observations=[MetricObservation(**observation_kwargs(value=0))],
    )
    assert zero.observations[0].value == 0.0
    assert StationTrafficData(station_id="0222", missing_data=["exit_traffic: API 미지원"]).observations == []
