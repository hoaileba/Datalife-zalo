from __future__ import annotations

from datetime import date, datetime

import pytest

from datamate import Clock, fmt, parse_date, parse_datetime, parse_money, parse_number
from datamate.norm import round2, round_money


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234,500", 1234500),
        ("28.970.000đ", 28970000),
        ("35k", 35000),
        ("1,5tr", 1500000),
        ("(1.500)", -1500),
        ("8,000.0000", 8000),
        ("45.000", 45000),
        ("1 phần", 1),
        (45000, 45000),
        ("-1", -1),
    ],
)
def test_parse_money(raw: object, expected: int) -> None:
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw,expected", [("1.5", 1.5), ("1,5", 1.5), ("1.500", 1500.0), ("2 kg", 2.0), ("-3", -3.0)])
def test_parse_number(raw: str, expected: float) -> None:
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("01/02/2026", date(2026, 2, 1)),
        ("2026-02-01", date(2026, 2, 1)),
        ("1 thg 7 2025", date(2025, 7, 1)),
        ("46054", date(2026, 2, 1)),
        ("15/08/26", date(2026, 8, 15)),
        ("ngày 1 tháng 7 năm 2025", date(2025, 7, 1)),
    ],
)
def test_parse_date(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


def test_parse_datetime_keeps_time() -> None:
    assert parse_datetime("01/02/2026 14:35") == datetime(2026, 2, 1, 14, 35)


def test_week_starts_monday_and_this_week_ends_today() -> None:
    clock = Clock("2026-05-24")
    assert clock.as_of.isoweekday() == 7
    assert (clock.this_week().start, clock.this_week().end) == (date(2026, 5, 18), date(2026, 5, 24))


def test_last_week_is_full_monday_to_sunday() -> None:
    clock = Clock("2026-05-20")
    week = clock.last_week()
    assert (week.start, week.end) == (date(2026, 5, 11), date(2026, 5, 17))
    assert week.days == 7


def test_this_month_ends_today_and_last_month_matches_day_count() -> None:
    clock = Clock("2026-05-24")
    assert (clock.this_month().start, clock.this_month().end) == (date(2026, 5, 1), date(2026, 5, 24))
    assert (clock.last_month_same_days().start, clock.last_month_same_days().end) == (date(2026, 4, 1), date(2026, 4, 24))


def test_last_month_same_days_clamps_to_short_month() -> None:
    clock = Clock("2026-03-31")
    assert clock.last_month_same_days().end == date(2026, 2, 28)


def test_last_month_crosses_year() -> None:
    clock = Clock("2026-01-15")
    assert (clock.last_month_same_days().start, clock.last_month_same_days().end) == (date(2025, 12, 1), date(2025, 12, 15))


def test_last_n_days_includes_today() -> None:
    clock = Clock("2026-05-24")
    window = clock.last_n_days(7)
    assert (window.start, window.end) == (date(2026, 5, 18), date(2026, 5, 24))
    assert window.days == 7


def test_month_without_year_falls_back_to_previous_year() -> None:
    clock = Clock("2026-05-24")
    assert clock.month(5).start.year == 2026
    assert clock.month(7).start.year == 2025


def test_quarter_without_year_falls_back() -> None:
    clock = Clock("2026-05-24")
    assert clock.quarter(1).start == date(2026, 1, 1)
    assert clock.quarter(4).start == date(2025, 10, 1)


def test_tet_window_from_lunar_calendar() -> None:
    clock = Clock("2026-05-24")
    season = clock.tet(2026)
    assert (season.start, season.end) == (date(2026, 2, 10), date(2026, 2, 26))
    before = clock.before_tet(2026)
    assert before.end == date(2026, 2, 9)
    assert before.days == season.days


@pytest.mark.parametrize("hour,expected", [(5, None), (6, "sáng"), (13, "sáng"), (14, "chiều"), (21, "chiều"), (22, None)])
def test_shift_boundaries(hour: int, expected: str | None) -> None:
    clock = Clock("2026-05-24")
    assert clock.shift_of(datetime(2026, 5, 24, hour, 30)) == expected


def test_count_weekday_includes_empty_days() -> None:
    clock = Clock("2026-05-31")
    assert clock.this_month().count_weekday(7) == 5


def test_money_rounds_half_up() -> None:
    assert round_money(0.5) == 1
    assert round_money(-0.5) == -1
    assert round2(2.075) == 2.08


def test_answer_line_rejects_bad_formats() -> None:
    with pytest.raises(ValueError):
        fmt.answer_line("q", "number", "4820000")
    with pytest.raises(ValueError):
        fmt.answer_line("q", "boolean", "có")
    with pytest.raises(ValueError):
        fmt.answer_line("q", "list", "a, b")
    with pytest.raises(ValueError):
        fmt.answer_line("q", "table", {"columns": ["a"], "rows": [[1, 2]]})


def test_answer_line_shapes() -> None:
    assert fmt.answer_line("q", "abstain") == {"id": "q", "type": "abstain"}
    assert fmt.answer_line("q", "unanswerable", reason="ngoài khoảng dữ liệu") == {
        "id": "q",
        "type": "unanswerable",
        "answer": None,
        "reason": "ngoài khoảng dữ liệu",
    }
    assert fmt.month_answer((2025, 9)) == "2025-09"


@pytest.mark.parametrize(
    "raw,expected",
    [("19tr990", 19990000), ("20tr239", 20239000), ("28,585tr", 28585000), ("19tr5", 19500000), ("1.500k", 1500000)],
)
def test_parse_money_vietnamese_million_shorthand(raw: str, expected: int) -> None:
    assert parse_money(raw) == expected


def test_nan_is_a_real_brand_name_not_blank() -> None:
    from datamate import is_blank

    assert is_blank("Nan") is False
    assert is_blank("nan") is False
    assert is_blank("") is True
    assert is_blank(None) is True


def test_fold_key_matches_names_written_without_diacritics() -> None:
    from datamate import fold_key, name_key

    assert fold_key("Trà chanh (M)") == fold_key("Tra chanh (M)")
    assert fold_key("Đậu phộng") == fold_key("Dau phong")
    assert name_key("Trà chanh (M)") != name_key("Tra chanh (M)")


def test_drop_repeated_header_rows() -> None:
    import pandas as pd

    from datamate import drop_repeated_header_rows

    frame = pd.DataFrame(
        [["Mã đơn", "Ngày"], ["ORD1", "01/01/2025"], ["Mã đơn", "Ngày"], ["ORD2", "02/01/2025"]],
        columns=["Mã đơn", "Ngày"],
    )
    assert len(drop_repeated_header_rows(frame)) == 2
