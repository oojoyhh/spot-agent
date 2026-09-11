from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tools.calendar_utils import classify_day


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 9, 10), "weekday"),
        (date(2026, 9, 12), "weekend"),
        (date(2026, 8, 15), "holiday"),
        (date(2026, 8, 17), "holiday"),
        (datetime(2026, 10, 9, 18, tzinfo=ZoneInfo("Asia/Seoul")), "holiday"),
    ],
)
def test_classify_korean_day(value: date | datetime, expected: str) -> None:
    assert classify_day(value) == expected


def test_classify_day_rejects_other_types() -> None:
    with pytest.raises(TypeError):
        classify_day("2026-09-10")  # type: ignore[arg-type]
