from __future__ import annotations

import calendar as _cal
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, model_validator

from .calendar_vn import LunarCalendar, load_calendar
from .norm import parse_datetime

if TYPE_CHECKING:
    import pandas as pd

MORNING_SHIFT = (6, 0, 13, 59)
AFTERNOON_SHIFT = (14, 0, 21, 59)


class Period(BaseModel):
    """Khoảng ngày đóng hai đầu, gồm cả start và end."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: date
    end: date
    label: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        if self.end < self.start:
            raise ValueError(f"period end before start: {self.start}..{self.end}")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, moment: date | datetime | None) -> bool:
        if moment is None:
            return False
        day = moment.date() if isinstance(moment, datetime) else moment
        return self.start <= day <= self.end

    def overlaps(self, other: "Period") -> bool:
        return self.start <= other.end and other.start <= self.end

    def shift_back_same_length(self) -> "Period":
        length = self.days
        new_end = self.start - timedelta(days=1)
        return Period(start=new_end - timedelta(days=length - 1), end=new_end, label=f"{self.label} (kỳ trước)")

    def each_day(self) -> tuple[date, ...]:
        return tuple(self.start + timedelta(days=i) for i in range(self.days))

    def count_weekday(self, iso_weekday: int) -> int:
        return sum(1 for day in self.each_day() if day.isoweekday() == iso_weekday)

    def __str__(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


def last_day_of_month(year: int, month: int) -> int:
    return _cal.monthrange(year, month)[1]


def month_period(year: int, month: int) -> Period:
    return Period(start=date(year, month, 1), end=date(year, month, last_day_of_month(year, month)), label=f"{month}/{year}")


def quarter_period(year: int, quarter: int) -> Period:
    if not 1 <= quarter <= 4:
        raise ValueError(f"quarter out of range: {quarter}")
    first = 3 * (quarter - 1) + 1
    return Period(start=date(year, first, 1), end=date(year, first + 2, last_day_of_month(year, first + 2)), label=f"Q{quarter}/{year}")


def year_period(year: int) -> Period:
    return Period(start=date(year, 1, 1), end=date(year, 12, 31), label=str(year))


class Clock:
    """Mọi cách nói thời gian của rulebook §2, neo vào as_of_date của một câu hỏi."""

    def __init__(self, as_of: date | str, *, calendar: LunarCalendar | None = None) -> None:
        self.as_of = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        self._calendar = calendar or load_calendar()

    @property
    def calendar(self) -> LunarCalendar:
        return self._calendar

    def day(self, moment: date | str) -> Period:
        target = date.fromisoformat(moment) if isinstance(moment, str) else moment
        return Period(start=target, end=target, label=target.isoformat())

    def between(self, start: date | str, end: date | str) -> Period:
        first = date.fromisoformat(start) if isinstance(start, str) else start
        last = date.fromisoformat(end) if isinstance(end, str) else end
        return Period(start=first, end=last, label=f"{first.isoformat()}..{last.isoformat()}")

    def today(self) -> Period:
        return self.day(self.as_of)

    def yesterday(self) -> Period:
        return self.day(self.as_of - timedelta(days=1))

    def until(self, moment: date | str | None = None, *, since: date | None = None) -> Period:
        target = self.as_of if moment is None else (date.fromisoformat(moment) if isinstance(moment, str) else moment)
        return Period(start=since or date(1900, 1, 1), end=target, label=f"đến hết {target.isoformat()}")

    def last_n_days(self, n: int) -> Period:
        if n < 1:
            raise ValueError(f"n must be positive: {n}")
        return Period(start=self.as_of - timedelta(days=n - 1), end=self.as_of, label=f"{n} ngày gần nhất")

    def this_week(self) -> Period:
        monday = self.as_of - timedelta(days=self.as_of.isoweekday() - 1)
        return Period(start=monday, end=self.as_of, label="tuần này")

    def last_week(self) -> Period:
        monday = self.as_of - timedelta(days=self.as_of.isoweekday() - 1)
        prev_monday = monday - timedelta(days=7)
        return Period(start=prev_monday, end=prev_monday + timedelta(days=6), label="tuần trước")

    def this_month(self) -> Period:
        return Period(start=date(self.as_of.year, self.as_of.month, 1), end=self.as_of, label="tháng này")

    def last_month_same_days(self) -> Period:
        year, month = (self.as_of.year, self.as_of.month - 1) if self.as_of.month > 1 else (self.as_of.year - 1, 12)
        cap = last_day_of_month(year, month)
        return Period(start=date(year, month, 1), end=date(year, month, min(self.as_of.day, cap)), label="tháng trước (cùng số ngày)")

    def last_month_full(self) -> Period:
        year, month = (self.as_of.year, self.as_of.month - 1) if self.as_of.month > 1 else (self.as_of.year - 1, 12)
        return month_period(year, month)

    def this_month_full(self) -> Period:
        return month_period(self.as_of.year, self.as_of.month)

    def year_to_date(self) -> Period:
        return Period(start=date(self.as_of.year, 1, 1), end=self.as_of, label="từ đầu năm")

    def month(self, month: int, year: int | None = None) -> Period:
        if year is not None:
            return month_period(year, month)
        candidate = month_period(self.as_of.year, month)
        if candidate.start > self.as_of:
            return month_period(self.as_of.year - 1, month)
        return candidate

    def quarter(self, quarter: int, year: int | None = None) -> Period:
        if year is not None:
            return quarter_period(year, quarter)
        candidate = quarter_period(self.as_of.year, quarter)
        if candidate.start > self.as_of:
            return quarter_period(self.as_of.year - 1, quarter)
        return candidate

    def tet(self, year: int) -> Period:
        start = self._calendar.to_solar(lunar_day=23, lunar_month=12, lunar_year=year - 1)
        end = self._calendar.to_solar(lunar_day=10, lunar_month=1, lunar_year=year)
        return Period(start=start, end=end, label=f"Tết {year}")

    def before_tet(self, year: int) -> Period:
        season = self.tet(year)
        length = season.days
        end = season.start - timedelta(days=1)
        return Period(start=end - timedelta(days=length - 1), end=end, label=f"trước Tết {year}")

    def shift_of(self, moment: datetime | None) -> str | None:
        if moment is None:
            return None
        minutes = moment.hour * 60 + moment.minute
        if MORNING_SHIFT[0] * 60 <= minutes <= MORNING_SHIFT[2] * 60 + MORNING_SHIFT[3]:
            return "sáng"
        if AFTERNOON_SHIFT[0] * 60 <= minutes <= AFTERNOON_SHIFT[2] * 60 + AFTERNOON_SHIFT[3]:
            return "chiều"
        return None

    def visible(self, moment: date | datetime | None) -> bool:
        if moment is None:
            return False
        day = moment.date() if isinstance(moment, datetime) else moment
        return day <= self.as_of

    def visible_rows(self, frame: pd.DataFrame, column: str) -> pd.DataFrame:
        import pandas as pd

        if column not in frame.columns:
            raise ValueError(f"no column {column!r}, columns are {list(frame.columns)}")
        moments = [None if pd.isna(value) else parse_datetime(value) for value in frame[column]]
        unreadable = [index for index, moment in enumerate(moments) if moment is None]
        if unreadable:
            first = frame[column].iloc[unreadable[0]]
            raise ValueError(f"{len(unreadable)} rows of {column!r} have no readable date, first {first!r}; drop subtotal rows or fill_group first")
        return frame[[self.visible(moment) for moment in moments]].copy()
