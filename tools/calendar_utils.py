"""대한민국 날짜의 평일·주말·공휴일 분류."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

import holidays

from models.schemas import DayType


@lru_cache(maxsize=32)
def _korean_holidays(year: int) -> holidays.HolidayBase:
    """대체공휴일을 포함한 해당 연도의 대한민국 공휴일을 반환한다."""
    return holidays.country_holidays("KR", years=year, observed=True)


def classify_day(value: date | datetime) -> DayType:
    """공휴일, 주말, 평일 순으로 하나의 day_type을 결정한다."""
    target = value.date() if isinstance(value, datetime) else value
    if not isinstance(target, date):
        raise TypeError("value는 date 또는 datetime이어야 합니다.")
    if target in _korean_holidays(target.year):
        return "holiday"
    if target.weekday() >= 5:
        return "weekend"
    return "weekday"
