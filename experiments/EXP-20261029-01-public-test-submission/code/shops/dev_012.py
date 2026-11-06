from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, fmt, parse_date, parse_money, squeeze
from datamate.fmt import load_questions, write_answers
from datamate.tabio import census, drop_subtotal_rows

SHOP = "dev_012"
EXPERIMENT_ROOT = CODE_ROOT.parent
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data") / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
BOOK_PATH = DATA_DIR / "SoSuaXe.xlsx"
STAFF_PATH = DATA_DIR / "DanhSachTho.xlsx"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"
DICTIONARY_PATH = EXPERIMENT_ROOT / "logs" / f"{SHOP}-lamgi-dictionary.json"

HEADER_ROW = 1
KEY_COLUMNS = ("Xe", "Làm gì", "Thợ", "Tiền")
WARRANTY_NOTE = "bảo hành"
VEHICLE_PATTERN = re.compile(r"^(.*?)\s*(\d{2}[A-Z]\d-\d{3}\.\d{2})\s*$")
JOB_SPLIT = re.compile(r"[,+]")
STAFF_PREFIX = re.compile(r"^(?:a\.|a\s+)", re.IGNORECASE)

JOB_ELECTRIC = "sửa điện"
JOB_GEAR_OIL = "thay nhớt láp"
JOB_PATCH = "vá ruột"

JOB_TOKENS: dict[str, tuple[str, ...]] = {
    "bảo dưỡng": ("BD", "bdtq", "bảo dưỡng", "bảo dưỡng xe"),
    "thay nhớt máy": (
        "nhớt", "thay nhớt", "nhớt hãng", "nhớt Honda",
        "Castrol", "nhớt Castrol", "nhớt Castrol Power1", "thay nhớt Castrol",
        "Motul", "nhớt Motul", "nhớt Motul ga", "thay nhớt Motul",
        "Shell 1L", "nhớt Shell", "thay nhớt Shell",
    ),
    JOB_GEAR_OIL: ("láp", "nhớt láp", "thay nhớt láp", "nhớt hộp số"),
    JOB_PATCH: ("vá", "vá ruột", "vá xe"),
    "thay ruột": ("ruột", "ruột xe", "thay ruột"),
    "thay vỏ": ("thay vỏ", "vỏ xe", "vỏ Casumina"),
    JOB_ELECTRIC: ("sửa điện", "làm điện"),
    "thay bóng đèn": ("bóng đèn", "thay bóng đèn", "đèn pha"),
    "thay ắc quy": ("bình", "bình GS", "thay bình", "ắc quy"),
    "bugi": ("bu gi", "bugi", "thay bugi"),
    "lọc gió": ("lọc gió", "thay lọc gió"),
    "dây curoa": ("curoa", "dây cu roa", "dây curoa"),
    "nước làm mát": ("nước làm mát", "nước mát", "thay nước mát"),
    "nhông sên dĩa": ("bộ nhông xích", "nhông sên dĩa", "NSD"),
    "chỉnh sên": ("chỉnh sên", "cân sên", "tăng sên"),
    "vệ sinh nồi": ("làm nồi", "vs nồi", "vệ sinh nồi"),
    "vệ sinh kim phun": ("rửa kim phun", "vs kim phun", "vệ sinh kim phun"),
    "rửa xe": ("rửa", "rửa xe"),
    "bố thắng trước": ("bố trước", "bố thắng trước", "má phanh trước"),
    "bố thắng sau": ("bố sau", "bố thắng sau", "má phanh sau"),
}

WARRANTY_TOKENS: dict[str, tuple[str, ...]] = {
    "bugi": ("BH bugi", "bảo hành bugi"),
    "thay ắc quy": ("BH bình", "bảo hành bình", "bảo hành ắc quy"),
    "bố thắng": ("BH bố thắng", "bảo hành bố thắng", "bảo hành má phanh"),
    "dây curoa": ("BH curoa", "bảo hành curoa"),
    "nhông sên dĩa": ("BH nhông sên dĩa", "bảo hành NSD"),
    "thay ruột": ("BH ruột", "bảo hành ruột"),
    JOB_PATCH: ("BH vá", "bảo hành vá"),
    "thay vỏ": ("BH vỏ", "bảo hành vỏ"),
    JOB_ELECTRIC: ("BH điện", "bảo hành điện"),
}

MODEL_LINES: dict[str, str] = {
    "vision": "Vision", "vision 110": "Vision",
    "ab": "Air Blade", "air blade": "Air Blade", "airblade": "Air Blade",
    "lead": "Lead",
    "sirius": "Sirius", "sirius fi": "Sirius",
    "alpha": "Wave Alpha", "wave alpha": "Wave Alpha", "wave α": "Wave Alpha",
    "future": "Future", "future 125": "Future",
    "grande": "Grande",
    "janus": "Janus",
    "ex": "Exciter", "exciter": "Exciter",
    "vario": "Vario", "vario 125": "Vario",
    "sh mode": "SH Mode", "shmode": "SH Mode",
    "rsx": "Wave RSX", "wave rsx": "Wave RSX",
    "winner": "Winner", "winner x": "Winner",
}


def token_dictionary() -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    for job, tokens in JOB_TOKENS.items():
        for token in tokens:
            entries[token] = {"job": job, "kind": "work"}
    for job, tokens in WARRANTY_TOKENS.items():
        for token in tokens:
            if token in entries:
                raise ValueError(f"token in two classes: {token}")
            entries[token] = {"job": job, "kind": "warranty"}
    return entries


def load_staff() -> dict[str, tuple[str, float]]:
    raw = pd.read_excel(STAFF_PATH, dtype=object)
    roster: dict[str, tuple[str, float]] = {}
    for _, row in raw.iterrows():
        full = squeeze(row["Họ tên"])
        roster[full.split(" ")[-1]] = (full, float(row["Hoa hồng (%)"]))
    return roster


def staff_full_name(raw: Any, roster: dict[str, tuple[str, float]]) -> str:
    short = STAFF_PREFIX.sub("", squeeze(raw)).strip()
    if short not in roster:
        raise ValueError(f"unknown staff: {raw!r}")
    return roster[short][0]


def read_book_raw() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for sheet in pd.ExcelFile(BOOK_PATH).sheet_names:
        raw = pd.read_excel(BOOK_PATH, sheet_name=sheet, header=None, dtype=object)
        body = raw.iloc[HEADER_ROW + 1 :].copy()
        body.columns = [squeeze(c) for c in raw.iloc[HEADER_ROW]]
        body["sheet"] = sheet
        frames.append(body)
    return pd.concat(frames, ignore_index=True)


def load_book() -> pd.DataFrame:
    dictionary = token_dictionary()
    roster = load_staff()
    frame = drop_subtotal_rows(read_book_raw(), key_columns=list(KEY_COLUMNS))
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        day = parse_date(row["Ngày"])
        money = parse_money(row["Tiền"])
        vehicle = VEHICLE_PATTERN.match(squeeze(row["Xe"]))
        if day is None or money is None or vehicle is None:
            raise ValueError(f"unparseable row: {row.to_dict()!r}")
        line = MODEL_LINES.get(vehicle.group(1).casefold())
        if line is None:
            raise ValueError(f"unknown model: {vehicle.group(1)!r}")
        tokens = tuple(t.strip() for t in JOB_SPLIT.split(squeeze(row["Làm gì"])))
        unknown = [t for t in tokens if t not in dictionary]
        if unknown:
            raise ValueError(f"unknown job tokens: {unknown}")
        note = "" if pd.isna(row["Ghi chú"]) else squeeze(row["Ghi chú"])
        warranty = note.startswith(WARRANTY_NOTE)
        token_warranty = any(dictionary[t]["kind"] == "warranty" for t in tokens)
        if warranty != token_warranty or warranty != (money == 0):
            raise ValueError(f"warranty signals disagree: {row.to_dict()!r}")
        records.append({
            "day": day,
            "plate": vehicle.group(2),
            "line": line,
            "jobs": frozenset(dictionary[t]["job"] for t in tokens),
            "warranty": warranty,
            "staff": staff_full_name(row["Thợ"], roster),
            "money": money,
        })
    return pd.DataFrame.from_records(records)


class Shop:
    """Sổ sửa xe dev_012 đã chuẩn hoá: mỗi dòng một phiếu."""

    def __init__(self, book: pd.DataFrame) -> None:
        self.book = book
        self.roster = {full: pct for full, pct in load_staff().values()}

    def tickets(self, period: Period) -> pd.DataFrame:
        mask = (self.book["day"] >= period.start) & (self.book["day"] <= period.end)
        return self.book[mask]

    def paid(self, period: Period) -> pd.DataFrame:
        frame = self.tickets(period)
        return frame[~frame["warranty"]]

    def revenue(self, period: Period) -> int:
        return int(self.tickets(period)["money"].sum())

    def percent_change(self, current: Period, previous: Period) -> float:
        before = self.revenue(previous)
        if before == 0:
            raise ValueError("previous revenue is zero")
        return fmt.percent((self.revenue(current) - before) / before * 100)

    def ticket_count(self, period: Period) -> int:
        return len(self.tickets(period))

    def warranty_count(self, period: Period) -> int:
        return int(self.tickets(period)["warranty"].sum())

    def average_paid_ticket(self, period: Period) -> int:
        paid = self.paid(period)
        if paid.empty:
            raise ValueError("no paid tickets in period")
        return fmt.money(paid["money"].sum() / len(paid))

    def warranty_rate(self, period: Period) -> float:
        paid = len(self.paid(period))
        if paid == 0:
            raise ValueError("no paid tickets in period")
        return fmt.percent(self.warranty_count(period) / paid * 100)

    def job_visits(self, period: Period, job: str) -> int:
        paid = self.paid(period)
        return int(paid["jobs"].map(lambda jobs: job in jobs).sum())

    def distinct_cars(self, period: Period, line: str) -> int:
        frame = self.tickets(period)
        return int(frame[frame["line"] == line]["plate"].nunique())

    def regular_cars(self, period: Period) -> int:
        visits = self.paid(period)["plate"].value_counts()
        return int((visits >= 2).sum())

    def staff_revenue(self, period: Period, staff: str) -> int:
        frame = self.tickets(period)
        return int(frame[frame["staff"] == staff]["money"].sum())

    def staff_tickets(self, period: Period, staff: str) -> int:
        frame = self.tickets(period)
        return int((frame["staff"] == staff).sum())

    def commissions(self, period: Period) -> tuple[tuple[str, int], ...]:
        totals = self.tickets(period).groupby("staff")["money"].sum()
        rows = [(staff, fmt.money(float(total) * self.roster[staff] / 100)) for staff, total in totals.items()]
        return tuple(sorted(rows, key=lambda r: (-r[1], r[0])))

    def top_staff(self, period: Period, measure: str) -> str:
        frame = self.tickets(period)
        if measure == "tickets":
            scores = frame.groupby("staff").size()
        elif measure == "revenue":
            scores = frame.groupby("staff")["money"].sum()
        elif measure == "working_days":
            scores = frame.groupby("staff")["day"].nunique()
        elif measure == "commission":
            return self.commissions(period)[0][0]
        else:
            raise ValueError(f"unsupported measure: {measure}")
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def staff_scores(self, period: Period) -> dict[str, dict[str, Any]]:
        frame = self.tickets(period)
        return {
            "tickets": dict(frame.groupby("staff").size()),
            "revenue": dict(frame.groupby("staff")["money"].sum()),
            "working_days": dict(frame.groupby("staff")["day"].nunique()),
        }

    def top_line_by_revenue(self, period: Period) -> str:
        scores = self.tickets(period).groupby("line")["money"].sum()
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def top_day_by_revenue(self, period: Period) -> date:
        scores = self.tickets(period).groupby("day")["money"].sum()
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def weekday_average_tickets(self, period: Period, iso_weekday: int) -> float:
        days = period.count_weekday(iso_weekday)
        frame = self.tickets(period)
        hits = int(frame["day"].map(lambda d: d.isoweekday() == iso_weekday).sum())
        return fmt.average(hits / days)


PHUC = "Đoàn Bảo Phúc"
AN = "Đàm Lan An"
DAT = "Hà Loan Đạt"
DUC = "Lương Chi Đức"
COMMISSION_COLUMNS = ("tho", "hoa_hong")
WEDNESDAY = 3
TUESDAY = 2


def commission_table(shop: Shop, period: Period) -> dict[str, Any]:
    return fmt.table(columns=COMMISSION_COLUMNS, rows=shop.commissions(period))


def build_answers(shop: Shop) -> dict[str, Callable[[Clock], tuple[str, Any]]]:
    return {
        "q_027f5441831d": lambda c: ("number", dict(shop.commissions(c.month(8, 2025)))[PHUC]),
        "q_05cde771f4c3": lambda c: ("number", shop.average_paid_ticket(c.month(2, 2026))),
        "q_06b7f437fcc4": lambda c: ("number", shop.staff_revenue(c.this_month(), AN)),
        "q_07e2508ad671": lambda c: ("number", shop.distinct_cars(c.this_month(), "SH Mode")),
        "q_1205eaa6091a": lambda c: ("percent", shop.percent_change(c.month(8, 2025), c.month(7, 2025))),
        "q_1c0046277ff9": lambda c: ("table", commission_table(shop, c.month(7, 2026))),
        "q_20b7bbf203c7": lambda c: ("table", commission_table(shop, c.month(3, 2026))),
        "q_2536e243a16c": lambda c: ("number", shop.revenue(c.quarter(2, 2026))),
        "q_2e00e336cad2": lambda c: ("number", shop.ticket_count(c.this_month())),
        "q_31cad30c7e96": lambda c: ("number", shop.revenue(c.month(2, 2026))),
        "q_32733a8ce625": lambda c: ("string", shop.top_line_by_revenue(c.month(10, 2025))),
        "q_33cb3a334a80": lambda c: ("number", shop.staff_tickets(c.month(8, 2025), DAT)),
        "q_34a5b4766a27": lambda c: ("number", shop.average_paid_ticket(c.month(8, 2025))),
        "q_35b891c4eebe": lambda c: ("unanswerable", None),
        "q_36edc7d2e347": lambda c: ("string", shop.top_staff(c.month(3, 2026), "tickets")),
        "q_3da612131082": lambda c: ("string", shop.top_staff(c.month(2, 2026), "commission")),
        "q_3e6a7564332d": lambda c: ("date", fmt.day_answer(shop.top_day_by_revenue(c.month(10, 2025)))),
        "q_4067c5f50ef7": lambda c: ("number", shop.ticket_count(c.month(2, 2026))),
        "q_40a6843b2c37": lambda c: ("number", shop.revenue(c.yesterday())),
        "q_4375c623b7c7": lambda c: ("date", fmt.day_answer(shop.top_day_by_revenue(c.month(1)))),
        "q_4d15340145ad": lambda c: ("date", fmt.day_answer(shop.top_day_by_revenue(c.month(8, 2026)))),
        "q_4e280a1755de": lambda c: ("number", shop.job_visits(c.month(8, 2025), JOB_ELECTRIC)),
        "q_508b7320c153": lambda c: ("number", shop.revenue(c.quarter(3, 2025))),
        "q_569dcd86abb4": lambda c: ("number", shop.weekday_average_tickets(c.month(3, 2026), WEDNESDAY)),
        "q_5ec7806c7f29": lambda c: ("number", shop.distinct_cars(c.month(1, 2026), "Air Blade")),
        "q_6b5bd6d88cc7": lambda c: ("percent", shop.warranty_rate(c.quarter(4, 2025))),
        "q_78126a171991": lambda c: ("number", shop.revenue(c.today())),
        "q_79b2abb21862": lambda c: ("number", shop.revenue(c.yesterday())),
        "q_7de8d58e315c": lambda c: ("number", shop.job_visits(c.month(9, 2025), JOB_GEAR_OIL)),
        "q_7f91e434b0fc": lambda c: ("number", shop.regular_cars(c.month(10, 2025))),
        "q_82711851c76a": lambda c: ("number", shop.staff_tickets(c.month(5, 2026), PHUC)),
        "q_8ce765944937": lambda c: ("number", shop.weekday_average_tickets(c.this_month(), TUESDAY)),
        "q_99f979b5d0b4": lambda c: ("percent", shop.percent_change(c.month(7, 2026), c.month(6, 2026))),
        "q_9f2824253517": lambda c: ("number", shop.staff_tickets(c.this_month(), AN)),
        "q_a225dc12182c": lambda c: ("string", shop.top_staff(c.month(9, 2025), "working_days")),
        "q_ad512cd0cb75": lambda c: ("string", shop.top_staff(c.month(3, 2026), "revenue")),
        "q_b127103da0d2": lambda c: ("number", shop.staff_revenue(c.month(4, 2026), DUC)),
        "q_b3059f66db30": lambda c: ("string", shop.top_staff(c.this_month(), "tickets")),
        "q_b342fe1e1211": lambda c: ("string", shop.top_staff(c.month(4, 2026), "revenue")),
        "q_b6d750b9ba50": lambda c: ("number", shop.distinct_cars(c.month(12, 2025), "Wave Alpha")),
        "q_c3158f13ca1c": lambda c: ("number", shop.regular_cars(Period(start=date(2025, 9, 1), end=date(2025, 11, 30)))),
        "q_c38425d8aec8": lambda c: ("number", shop.job_visits(c.this_month(), JOB_PATCH)),
        "q_c69505022fd3": lambda c: ("table", commission_table(shop, c.month(11, 2025))),
        "q_c803650fe803": lambda c: ("number", shop.warranty_count(c.quarter(2, 2026))),
        "q_d3b768308def": lambda c: ("percent", shop.percent_change(c.month(4, 2026), c.month(3, 2026))),
        "q_e4fd11ebbadf": lambda c: ("number", shop.revenue(c.month(5, 2026))),
        "q_eb606434a18e": lambda c: ("number", shop.warranty_count(c.month(8, 2026))),
        "q_ec8d9cfa0f6b": lambda c: ("number", shop.average_paid_ticket(c.month(1, 2026))),
        "q_f3a93a869037": lambda c: ("number", shop.staff_revenue(c.month(7, 2026), DAT)),
        "q_f9c80cc2d330": lambda c: ("number", shop.revenue(c.month(11, 2025))),
    }


def write_dictionary() -> None:
    DICTIONARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    DICTIONARY_PATH.write_text(json.dumps(token_dictionary(), ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    write_dictionary()
    print(census(read_book_raw(), key_columns=list(KEY_COLUMNS)))
    shop = Shop(load_book())
    handlers = build_answers(shop)
    lines: list[dict[str, Any]] = []
    for question in load_questions(QUESTIONS_PATH):
        qid = question["id"]
        kind, value = handlers[qid](Clock(question["as_of_date"]))
        lines.append(fmt.answer_line(qid, kind, value))
        print(qid, kind, json.dumps(value, ensure_ascii=False), "|", question["question"])
    print("written", write_answers(ANSWERS_PATH, lines))
    print(Counter(line["type"] for line in lines))


if __name__ == "__main__":
    main()
