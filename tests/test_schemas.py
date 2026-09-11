"""공통 모델 검증 테스트.

담당: 역할 4 · 효주
실행 (저장소 루트에서): python -m pytest tests/test_schemas.py
외부 호출 없음.
"""

import json
from datetime import date

import pytest
from pydantic import ValidationError

from models.schemas import (
    AcademyDemandData,
    AnalysisPeriod,
    AreaIdentity,
    ErrorCode,
    MetricObservation,
    NearbyStation,
    StationTrafficData,
    ToolResult,
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
    first = StationTrafficData(station_id="1")
    second = StationTrafficData(station_id="2")
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
