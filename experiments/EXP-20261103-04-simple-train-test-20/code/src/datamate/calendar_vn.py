from __future__ import annotations

import csv
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

CALENDAR_ENV = "DATAMATE_CALENDAR"


class LunarCalendar:
    """Tra cứu hai chiều dương lịch và âm lịch, nạp từ calendar.csv của bộ đề."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise ValueError(f"calendar not found: {self._path}")
        solar_of: dict[tuple[int, int, int, bool], date] = {}
        lunar_of: dict[date, tuple[int, int, int, bool]] = {}
        holidays: dict[date, str] = {}
        with self._path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                solar = date.fromisoformat(row["date"])
                key = (
                    int(row["lunar_day"]),
                    int(row["lunar_month"]),
                    int(row["lunar_year"]),
                    row["lunar_leap"].strip().casefold() == "true",
                )
                solar_of.setdefault(key, solar)
                lunar_of[solar] = key
                if row.get("holiday", "").strip():
                    holidays[solar] = row["holiday"].strip()
        self._solar_of = solar_of
        self._lunar_of = lunar_of
        self._holidays = holidays
        self._min = min(lunar_of)
        self._max = max(lunar_of)

    @property
    def covers(self) -> tuple[date, date]:
        return (self._min, self._max)

    def to_solar(self, *, lunar_day: int, lunar_month: int, lunar_year: int, leap: bool = False) -> date:
        key = (lunar_day, lunar_month, lunar_year, leap)
        if key not in self._solar_of:
            raise ValueError(f"lunar date not in calendar: {key}")
        return self._solar_of[key]

    def to_lunar(self, solar: date) -> tuple[int, int, int, bool]:
        if solar not in self._lunar_of:
            raise ValueError(f"solar date not in calendar: {solar}")
        return self._lunar_of[solar]

    def holiday(self, solar: date) -> str | None:
        return self._holidays.get(solar)


@lru_cache(maxsize=4)
def load_calendar(path: str | None = None) -> LunarCalendar:
    chosen = path or os.environ.get(CALENDAR_ENV)
    if not chosen:
        raise ValueError(f"calendar path not set: pass a path or set {CALENDAR_ENV}")
    return LunarCalendar(chosen)
