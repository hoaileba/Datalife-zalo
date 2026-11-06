from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, fmt, fold_key, parse_date, parse_money, squeeze
from datamate.fmt import load_questions, write_answers
from datamate.tabio import drop_subtotal_rows, sheet_names

SHOP = "dev_014"
EXPERIMENT_ROOT = CODE_ROOT.parent
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data") / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"
SALES_PATH = DATA_DIR / "SoBanHang.xlsx"
DEBT_PATH = DATA_DIR / "SoNo.xlsx"
TRADEIN_PATH = DATA_DIR / "ThuMayCu.xlsx"

ABBREV_SHEET = "Ghi tắt"
KIND_NEW = "máy mới"
KIND_USED = "máy cũ"
KIND_ACCESSORY = "phụ kiện"
PHONE_KINDS = frozenset({KIND_NEW, KIND_USED})

STATUS_DONE = "hoàn thành"
STATUS_RETURNED = "trả hàng"
STATUS_BY_NOTE = {
    "trả lại hàng": STATUS_RETURNED,
    "khách mang trả": STATUS_RETURNED,
    "khách trả lại": STATUS_RETURNED,
}

STORAGE_PATTERN = re.compile(r"^(.*?)\s+\d+\s*GB\b", re.IGNORECASE)
DATA_START = date(2025, 7, 1)
DATA_END = date(2026, 9, 30)


def _cell_text(value: Any) -> str:
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else squeeze(value)


def _money_or_zero(value: Any) -> int:
    text = _cell_text(value)
    if text == "":
        return 0
    parsed = parse_money(text)
    if parsed is None:
        raise ValueError(f"unparseable money: {value!r}")
    return parsed


def _money(value: Any) -> int:
    parsed = parse_money(value)
    if parsed is None:
        raise ValueError(f"unparseable money: {value!r}")
    return parsed


def _read_sheet(path: Path, sheet: str, *, header_row: int) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    body = raw.iloc[header_row + 1 :].copy()
    body.columns = [squeeze(c) for c in raw.iloc[header_row]]
    return body.dropna(how="all").reset_index(drop=True)


def phone_line(item: str) -> str:
    """Dòng máy theo rulebook §6: phần trước dung lượng GB, không có GB thì cả tên."""
    match = STORAGE_PATTERN.match(item)
    return squeeze(match.group(1)) if match else squeeze(item)


def phone_brand(item: str) -> str:
    first = squeeze(item).split(" ")[0]
    return "Apple" if first.lower() == "iphone" else first


def customer_key(name: Any, phone: Any) -> str:
    return f"{fold_key(name)}|{_cell_text(phone)}"


class Ledger:
    """Sổ bán, sổ thu máy cũ, sổ nợ, sổ góp, sổ bảo hành của dev_014 đã ingest và kiểm kê."""

    def __init__(self, data_dir: Path) -> None:
        if not data_dir.is_dir():
            raise ValueError(f"missing data dir: {data_dir}")
        self.catalog = self._load_catalog()
        self.lines = self._load_lines()
        self.tradeins = self._load_tradeins()
        self.orders = self._build_orders()
        self.debts, self.debt_payments = self._load_debts()
        self.contracts, self.instalments = self._load_contracts()
        self.warranty = self._load_warranty()

    def _load_catalog(self) -> dict[str, tuple[str, str]]:
        table = _read_sheet(SALES_PATH, ABBREV_SHEET, header_row=0)
        lookup: dict[str, tuple[str, str]] = {}
        for _, row in table.iterrows():
            entry = (squeeze(row["Tên hàng"]), squeeze(row["Loại"]))
            for alias in (row["Ghi tắt"], row["Tên hàng"]):
                key = fold_key(alias)
                if key in lookup and lookup[key] != entry:
                    raise ValueError(f"abbreviation collision: {alias}")
                lookup[key] = entry
        return lookup

    def _load_lines(self) -> pd.DataFrame:
        frames = []
        for sheet in sheet_names(SALES_PATH):
            if sheet == ABBREV_SHEET:
                continue
            body = _read_sheet(SALES_PATH, sheet, header_row=1)
            body["sheet"] = sheet
            frames.append(body)
        raw = pd.concat(frames, ignore_index=True)
        kept = drop_subtotal_rows(raw, key_columns=["STT"])
        self.subtotal_rows = len(raw) - len(kept)
        deduped = kept.drop_duplicates().reset_index(drop=True)
        self.duplicate_rows = len(kept) - len(deduped)
        lines = deduped.copy()
        lines["stt"] = lines["STT"].astype(int)
        lines["day"] = lines["Ngày"].map(parse_date)
        unknown = {h for h in lines["Hàng"] if fold_key(h) not in self.catalog}
        if unknown:
            raise ValueError(f"unmapped items: {sorted(unknown)}")
        lines["item"] = lines["Hàng"].map(lambda h: self.catalog[fold_key(h)][0])
        lines["kind"] = lines["Hàng"].map(lambda h: self.catalog[fold_key(h)][1])
        lines["qty"] = lines["SL"].astype(int)
        lines["amount"] = lines["Thành tiền"].map(_money)
        lines["discount"] = lines["Bớt"].map(_money_or_zero)
        lines["payable"] = lines["Khách trả"].map(_money)
        lines["note"] = lines["Ghi chú"].map(_cell_text)
        unknown_notes = {n for n in lines["note"] if n and n not in STATUS_BY_NOTE}
        if unknown_notes:
            raise ValueError(f"unclassified notes: {sorted(unknown_notes)}")
        lines["status"] = lines["note"].map(lambda n: STATUS_BY_NOTE.get(n, STATUS_DONE))
        lines["line"] = lines["item"].map(phone_line)
        lines["brand"] = lines["item"].map(phone_brand)
        lines["imeis"] = lines["IMEI"].map(lambda v: tuple(p.strip() for p in _cell_text(v).split("/") if p.strip()))
        bad = lines[lines["amount"] != lines["qty"] * lines["Giá"].map(_money)]
        if not bad.empty:
            raise ValueError(f"line amount != qty x price on {len(bad)} rows")
        return lines

    def _load_tradeins(self) -> pd.DataFrame:
        table = _read_sheet(TRADEIN_PATH, "Sheet1", header_row=0)
        table["stt"] = table["Trừ vào (STT sổ bán)"].astype(int)
        table["price"] = table["Giá thu"].map(_money)
        table["day"] = table["Ngày"].map(parse_date)
        if table["stt"].duplicated().any():
            raise ValueError("one sale order has two trade-ins")
        return table

    def _build_orders(self) -> pd.DataFrame:
        grouped = self.lines.groupby("stt")
        orders = pd.DataFrame(
            {
                "day": grouped["day"].first(),
                "revenue": grouped["amount"].sum(),
                "discount": grouped["discount"].first(),
                "payable": grouped["payable"].first(),
                "status": grouped["status"].first(),
                "customer": grouped["Khách"].first(),
            }
        )
        for column in ("day", "discount", "payable", "status"):
            if (grouped[column].nunique() > 1).any():
                raise ValueError(f"order-level column varies within order: {column}")
        orders["tradein"] = orders.index.map(dict(zip(self.tradeins["stt"], self.tradeins["price"]))).fillna(0).astype(int)
        mismatch = orders["revenue"] - orders["discount"] - orders["tradein"] - orders["payable"]
        if (mismatch != 0).any():
            raise ValueError(f"payable invariant fails on {int((mismatch != 0).sum())} orders")
        return orders

    def _load_debts(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        table = _read_sheet(DEBT_PATH, "Sổ nợ", header_row=0)
        table["stt"] = table["Ghi chú"].map(lambda s: int(re.search(r"\d+", str(s)).group()))
        heads = table[table["Ngày"].notna()].copy()
        heads["day"] = heads["Ngày"].map(parse_date)
        heads["owed"] = heads["Nợ"].map(_money)
        heads["customer"] = [customer_key(n, p) for n, p in zip(heads["Khách"], heads["SĐT"])]
        payments = table[table["Đã trả"].notna()].copy()
        payments["paid"] = payments["Đã trả"].map(_money)
        payments["paid_day"] = payments["Ngày trả"].map(parse_date)
        return heads.set_index("stt"), payments

    def _load_contracts(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        table = _read_sheet(DEBT_PATH, "Trả góp", header_row=0)
        table["stt"] = table["STT"].astype(int)
        heads = table[table["Ngày"].notna()].copy()
        heads["day"] = heads["Ngày"].map(parse_date)
        heads["price"] = heads["Giá"].map(_money)
        heads["upfront"] = heads["Trả trước"].map(_money)
        heads["terms"] = heads["Số kỳ"].astype(int)
        heads["instalment"] = heads["Góp/tháng"].map(_money)
        heads["due_day"] = heads["Hạn góp (ngày)"].astype(int)
        heads["customer"] = [customer_key(n, p) for n, p in zip(heads["Khách"], heads["SĐT"])]
        if (heads["price"] != heads["upfront"] + heads["terms"] * heads["instalment"]).any():
            raise ValueError("contract price != upfront + terms x instalment")
        payments = table[table["Đã góp"].notna()].copy()
        payments["paid"] = payments["Đã góp"].map(_money)
        payments["paid_day"] = payments["Ngày góp"].map(parse_date)
        return heads.set_index("stt"), payments

    def _load_warranty(self) -> pd.DataFrame:
        table = _read_sheet(DEBT_PATH, "Bảo hành", header_row=0)
        table["received"] = table["Ngày nhận"].map(parse_date)
        table["imei"] = table["IMEI"].map(_cell_text)
        sold_line = {imei: line for imeis, line in zip(self.lines["imeis"], self.lines["line"]) for imei in imeis}
        unmatched = set(table["imei"]) - set(sold_line)
        if unmatched:
            raise ValueError(f"warranty imei not in sales: {sorted(unmatched)}")
        table["line"] = table["imei"].map(sold_line)
        disagree = table[table["line"].map(fold_key) != table["Máy"].map(fold_key)]
        if not disagree.empty:
            raise ValueError(f"warranty model disagrees with sold line on {len(disagree)} rows")
        return table


def counted_orders(ledger: Ledger, period: Period) -> pd.DataFrame:
    """Đơn tính vào doanh thu §1: không huỷ, không trả, ngày đặt trong kỳ."""
    orders = ledger.orders
    mask = (orders["status"] != STATUS_RETURNED) & orders["day"].map(period.contains)
    return orders[mask]


def counted_lines(ledger: Ledger, period: Period) -> pd.DataFrame:
    stts = set(counted_orders(ledger, period).index)
    return ledger.lines[ledger.lines["stt"].isin(stts)]


def revenue(ledger: Ledger, period: Period) -> int:
    return int(counted_lines(ledger, period)["amount"].sum())


def pct_change(current: float, previous: float) -> float:
    if previous == 0:
        raise ValueError("previous period is zero")
    return fmt.percent((current - previous) / previous * 100)


def phone_lines(ledger: Ledger, period: Period) -> pd.DataFrame:
    lines = counted_lines(ledger, period)
    return lines[lines["kind"].isin(PHONE_KINDS)]


def top_phone_lines(ledger: Ledger, period: Period, k: int) -> list[str]:
    qty = phone_lines(ledger, period).groupby("line")["qty"].sum()
    ranked = sorted(qty.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > k and ranked[k - 1][1] == ranked[k][1]:
        raise ValueError(f"tie at rank {k}: {ranked[k - 1]} vs {ranked[k]}")
    return [name for name, _ in ranked[:k]]


def best_seller(lines: pd.DataFrame) -> str:
    qty = lines.groupby("item")["qty"].sum()
    ranked = sorted(qty.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        raise ValueError(f"tie for best seller: {ranked[:2]}")
    return ranked[0][0]


def payable_total(ledger: Ledger, period: Period) -> int:
    return int(counted_orders(ledger, period)["payable"].sum())


def payable_average(ledger: Ledger, period: Period) -> int:
    orders = counted_orders(ledger, period)
    return fmt.money(orders["payable"].sum() / len(orders))


def tradein_total(ledger: Ledger, period: Period) -> int:
    return int(counted_orders(ledger, period)["tradein"].sum())


def tradein_order_share(ledger: Ledger, period: Period) -> float:
    orders = counted_orders(ledger, period)
    return fmt.percent((orders["tradein"] > 0).sum() / len(orders) * 100)


def due_date(contract: pd.Series, term: int) -> date:
    start = contract["day"]
    month_index = start.month - 1 + term
    return date(start.year + month_index // 12, month_index % 12 + 1, int(contract["due_day"]))


def contract_state(ledger: Ledger, stt: int, as_of: date) -> dict[str, int]:
    contract = ledger.contracts.loc[stt]
    payments = ledger.instalments[(ledger.instalments["stt"] == stt) & (ledger.instalments["paid_day"] <= as_of)]
    paid = int(payments["paid"].sum())
    owed_total = int(contract["terms"] * contract["instalment"])
    dues = [due_date(contract, k) for k in range(1, int(contract["terms"]) + 1)]
    due_through_today = sum(1 for d in dues if d <= as_of)
    overdue_terms = sum(1 for d in dues if d < as_of)
    overdue_amount = max(0, overdue_terms * int(contract["instalment"]) - paid)
    return {
        "remaining": owed_total - paid,
        "due_through_today": due_through_today,
        "overdue_amount": overdue_amount,
    }


def open_contracts(ledger: Ledger, as_of: date) -> tuple[int, ...]:
    return tuple(stt for stt, row in ledger.contracts.iterrows() if row["day"] <= as_of)


def instalment_remaining_total(ledger: Ledger, as_of: date) -> int:
    return sum(contract_state(ledger, s, as_of)["remaining"] for s in open_contracts(ledger, as_of))


def instalment_overdue_total(ledger: Ledger, as_of: date) -> int:
    return sum(contract_state(ledger, s, as_of)["overdue_amount"] for s in open_contracts(ledger, as_of))


def overdue_customers(ledger: Ledger, as_of: date) -> int:
    keys = {
        ledger.contracts.loc[s, "customer"]
        for s in open_contracts(ledger, as_of)
        if contract_state(ledger, s, as_of)["overdue_amount"] > 0
    }
    return len(keys)


def contract_of(ledger: Ledger, name: str, as_of: date) -> int:
    matches = [s for s in open_contracts(ledger, as_of) if fold_key(ledger.contracts.loc[s, "Khách"]) == fold_key(name)]
    if len(matches) != 1:
        raise ValueError(f"expected one contract for {name}, got {matches}")
    return matches[0]


def debt_positions(ledger: Ledger, as_of: date) -> tuple[tuple[str, date, int], ...]:
    """Mọi khoản còn nợ > 0 lúc hết ngày as_of: sổ nợ và sổ góp, kèm khách và ngày đặt."""
    positions: list[tuple[str, date, int]] = []
    for stt, row in ledger.debts.iterrows():
        if row["day"] > as_of:
            continue
        paid = ledger.debt_payments[(ledger.debt_payments["stt"] == stt) & (ledger.debt_payments["paid_day"] <= as_of)]["paid"].sum()
        remaining = int(row["owed"] - paid)
        if remaining > 0:
            positions.append((row["customer"], row["day"], remaining))
    for stt in open_contracts(ledger, as_of):
        remaining = contract_state(ledger, stt, as_of)["remaining"]
        if remaining > 0:
            positions.append((ledger.contracts.loc[stt, "customer"], ledger.contracts.loc[stt, "day"], remaining))
    return tuple(positions)


def debt_by_age(ledger: Ledger, as_of: date) -> list[int]:
    buckets = [0, 0, 0]
    for _, day, remaining in debt_positions(ledger, as_of):
        age = (as_of - day).days
        buckets[0 if age <= 7 else 1 if age <= 15 else 2] += remaining
    return buckets


def warranty_visits(ledger: Ledger, period: Period) -> pd.DataFrame:
    return ledger.warranty[ledger.warranty["received"].map(period.contains)]


def warranty_rate(ledger: Ledger, period: Period) -> float:
    visits = len(warranty_visits(ledger, period))
    sold = int(phone_lines(ledger, period)["qty"].sum())
    return fmt.percent(visits / sold * 100)


def phones_sold_then_serviced(ledger: Ledger, period: Period, as_of: date) -> int:
    sold = {imei for imeis in phone_lines(ledger, period)["imeis"] for imei in imeis}
    serviced = set(ledger.warranty[ledger.warranty["received"] <= as_of]["imei"])
    return len(sold & serviced)


def top_warranty_line(ledger: Ledger, period: Period) -> str:
    counts = warranty_visits(ledger, period).groupby("line").size()
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        raise ValueError(f"tie for warranty line: {ranked[:2]}")
    return ranked[0][0]


def item_window_qty(ledger: Ledger, item: str, period: Period) -> int:
    lines = counted_lines(ledger, period)
    return int(lines[lines["item"] == item]["qty"].sum())


Answer = tuple[str, Any]


def build_answers(ledger: Ledger) -> dict[str, Callable[[Clock], Answer]]:
    def money(value: float) -> Answer:
        return ("number", fmt.money(value))

    def count(value: float) -> Answer:
        return ("number", fmt.count(value))

    def pct(value: float) -> Answer:
        return ("percent", value)

    def d(text: str) -> date:
        return date.fromisoformat(text)

    def phones_qty(c: Clock, period: Period, *, kinds: frozenset[str] = PHONE_KINDS) -> int:
        lines = phone_lines(ledger, period)
        return int(lines[lines["kind"].isin(kinds)]["qty"].sum())

    def phone_avg_price(period: Period) -> Answer:
        lines = phone_lines(ledger, period)
        return money(lines["amount"].sum() / lines["qty"].sum())

    def new_share(period: Period) -> Answer:
        lines = phone_lines(ledger, period)
        return pct(fmt.percent(lines[lines["kind"] == KIND_NEW]["amount"].sum() / lines["amount"].sum() * 100))

    def line_qty(period: Period, line_name: str) -> Answer:
        lines = phone_lines(ledger, period)
        return count(lines[lines["line"] == line_name]["qty"].sum())

    def item_amount(period: Period, item: str) -> Answer:
        lines = counted_lines(ledger, period)
        return money(lines[lines["item"] == item]["amount"].sum())

    def item_qty(period: Period, item: str) -> Answer:
        lines = counted_lines(ledger, period)
        return count(lines[lines["item"] == item]["qty"].sum())

    def avg_order_revenue(period: Period) -> Answer:
        orders = counted_orders(ledger, period)
        return money(orders["revenue"].sum() / len(orders))

    def samsung_share(period: Period) -> Answer:
        lines = phone_lines(ledger, period)
        return pct(fmt.percent(lines[lines["brand"] == "Samsung"]["qty"].sum() / lines["qty"].sum() * 100))

    def orders_at_least(period: Period, threshold: int) -> Answer:
        return count((counted_orders(ledger, period)["revenue"] >= threshold).sum())

    def debt_customers(as_of: date) -> Answer:
        return count(len({key for key, _, _ in debt_positions(ledger, as_of)}))

    def price_effect(c: Clock) -> Answer:
        start = d("2025-12-01")
        after = Period(start=start, end=start + timedelta(days=13), label="sau")
        before = Period(start=start - timedelta(days=14), end=start - timedelta(days=1), label="trước")
        item = "Cáp Type-C sang Lightning 1m"
        return pct(pct_change(item_window_qty(ledger, item, after), item_window_qty(ledger, item, before)))

    def new_phone_best(period: Period) -> Answer:
        lines = phone_lines(ledger, period)
        return ("string", best_seller(lines[lines["kind"] == KIND_NEW]))

    return {
        "q_0594583b3d46": lambda c: money(instalment_remaining_total(ledger, c.as_of)),
        "q_0b854610073b": lambda c: money(tradein_total(ledger, c.month(9, 2025))),
        "q_0d23cc65cc7a": lambda c: pct(pct_change(revenue(ledger, c.this_month()), revenue(ledger, c.last_month_same_days()))),
        "q_1019063a351e": lambda c: money(tradein_total(ledger, c.month(2, 2026))),
        "q_101a2b744e56": lambda c: count(contract_state(ledger, contract_of(ledger, "Tạ Dũng Long", c.as_of), c.as_of)["due_through_today"]),
        "q_16852a1ac5f7": lambda c: count(overdue_customers(ledger, c.as_of)),
        "q_220b5f8bc174": lambda c: pct(pct_change(revenue(ledger, c.month(3, 2026)), revenue(ledger, c.month(2, 2026)))),
        "q_25af2ef67065": lambda c: pct(warranty_rate(ledger, c.quarter(3, 2026))),
        "q_2710e38fa0d6": lambda c: item_amount(c.month(2, 2026), "Củ sạc nhanh 25W Samsung"),
        "q_2f8852d2a6bc": lambda c: money(revenue(ledger, c.year_to_date())),
        "q_31dad3219917": lambda c: money(revenue(ledger, c.year_to_date())),
        "q_32b653051a42": lambda c: count(phones_qty(c, c.month(8, 2025), kinds=frozenset({KIND_USED}))),
        "q_338d0179f66d": lambda c: count(overdue_customers(ledger, c.as_of)),
        "q_3751b6361499": lambda c: orders_at_least(c.month(5, 2026), 340_000),
        "q_3a9665052018": lambda c: pct(tradein_order_share(ledger, c.month(4, 2026))),
        "q_3ac94b30991c": lambda c: new_share(c.month(4, 2026)),
        "q_3fb7bbc8ec8a": lambda c: count(phones_qty(c, c.month(8, 2025))),
        "q_408c2137f088": lambda c: ("unanswerable", "shop không ghi giá vốn hay giá nhập hàng bán, không tính được lãi"),
        "q_4162fa76a222": lambda c: line_qty(c.this_month(), "iPhone 13"),
        "q_435a38fb843b": lambda c: money(contract_state(ledger, contract_of(ledger, "Ông Hiếu Anh", c.as_of), c.as_of)["remaining"]),
        "q_473593cb045c": lambda c: ("list", top_phone_lines(ledger, c.quarter(1, 2026), 3)),
        "q_4b82c6814a0d": lambda c: new_share(c.this_month()),
        "q_4c24acd737a8": lambda c: money(payable_total(ledger, c.month(2, 2026))),
        "q_4e1c4ca89508": lambda c: ("string", best_seller(counted_lines(ledger, c.tet(2026)))),
        "q_5176249df658": lambda c: avg_order_revenue(c.last_week()),
        "q_51b4d4e4e063": lambda c: money(instalment_remaining_total(ledger, c.as_of)),
        "q_527c4e439966": lambda c: count(overdue_customers(ledger, c.as_of)),
        "q_5a9e0b8dce13": lambda c: count(len(warranty_visits(ledger, c.quarter(1, 2026)))),
        "q_5c0acaa8786b": lambda c: money(contract_state(ledger, contract_of(ledger, "Ngô Nam Ngân", c.as_of), c.as_of)["remaining"]),
        "q_603c21ebef86": lambda c: pct(tradein_order_share(ledger, c.this_month())),
        "q_6a138cfe1257": lambda c: pct(pct_change(revenue(ledger, c.month(8, 2025)), revenue(ledger, c.month(7, 2025)))),
        "q_6d42e3d7b79b": lambda c: money(instalment_overdue_total(ledger, c.as_of)),
        "q_733500e5c7a7": price_effect,
        "q_763243ad81fd": lambda c: money(payable_total(ledger, c.month(12, 2025))),
        "q_7826ef06d11c": lambda c: ("list", top_phone_lines(ledger, c.month(1, 2026), 3)),
        "q_78b9ca050ca1": lambda c: money(payable_total(ledger, c.this_month())),
        "q_792e1070baaf": lambda c: samsung_share(c.month(10, 2025)),
        "q_7c6452fd1c4b": lambda c: ("unanswerable", "shop không ghi địa chỉ khách ở sổ nào"),
        "q_7c8c12f20aa2": lambda c: count(phones_sold_then_serviced(ledger, c.month(8, 2025), c.as_of)),
        "q_7cba4252429f": lambda c: avg_order_revenue(c.last_week()),
        "q_86a32a09633a": lambda c: money(tradein_total(ledger, c.month(8, 2025))),
        "q_8e44f654589f": lambda c: count(contract_state(ledger, contract_of(ledger, "Triệu Thu Trang", c.as_of), c.as_of)["due_through_today"]),
        "q_8e50e264d157": lambda c: phone_avg_price(c.this_month()),
        "q_917d6af4418e": lambda c: ("string", top_warranty_line(ledger, c.quarter(2, 2026))),
        "q_94f634ace6b1": lambda c: money(payable_average(ledger, c.month(8, 2025))),
        "q_9c2c85d9330d": lambda c: pct(pct_change(revenue(ledger, c.tet(2026)), revenue(ledger, c.before_tet(2026)))),
        "q_a883b37bc197": lambda c: count(len(warranty_visits(ledger, c.quarter(4, 2025)))),
        "q_a8d7ce013c6d": lambda c: money(instalment_overdue_total(ledger, c.as_of)),
        "q_b2eb16844a32": lambda c: count(phones_sold_then_serviced(ledger, c.month(7, 2026), c.as_of)),
        "q_b33016c0dd71": lambda c: money(instalment_overdue_total(ledger, c.as_of)),
        "q_b6abccb6b3cb": lambda c: item_qty(c.month(1, 2026), "Ốp lưng silicon iPhone"),
        "q_b9aab5c81568": lambda c: ("list", [revenue(ledger, c.month(m, 2026)) for m in (7, 8, 9)]),
        "q_c4da058cd902": lambda c: new_phone_best(c.month(2, 2026)),
        "q_d08785ea5577": lambda c: phone_avg_price(c.month(12, 2025)),
        "q_de76013dcb99": lambda c: money(revenue(ledger, c.tet(2026))),
        "q_e0ac213834f6": lambda c: money(payable_average(ledger, c.month(6, 2026))),
        "q_e2ad9e83d06a": lambda c: money(sum(r for _, _, r in debt_positions(ledger, c.as_of))),
        "q_e4fc0d18d409": lambda c: line_qty(c.month(1, 2026), "Xiaomi Redmi Note 14"),
        "q_e734e6e62c7c": lambda c: money(contract_state(ledger, contract_of(ledger, "Lương Khoa Hoàng", c.as_of), c.as_of)["remaining"]),
        "q_f30748b72898": lambda c: money(payable_average(ledger, c.month(8, 2026))),
        "q_f37ffc2cfd0c": lambda c: ("list", debt_by_age(ledger, c.as_of)),
        "q_fd38dda74f47": lambda c: money(revenue(ledger, c.month(1, 2026))),
        "q_ff9f21f3aa6c": lambda c: debt_customers(c.as_of),
    }


ABSTAIN: frozenset[str] = frozenset()


def main() -> int:
    ledger = Ledger(DATA_DIR)
    handlers = build_answers(ledger)
    lines = []
    for question in load_questions(QUESTIONS_PATH):
        qid = question["id"]
        if qid in ABSTAIN or qid not in handlers:
            lines.append(fmt.answer_line(qid, "abstain"))
            continue
        answer_type, value = handlers[qid](Clock(question["as_of_date"]))
        if answer_type == "unanswerable":
            lines.append(fmt.answer_line(qid, "unanswerable", reason=value))
        else:
            lines.append(fmt.answer_line(qid, answer_type, value))
    written = write_answers(ANSWERS_PATH, lines)
    for line in lines:
        print(line)
    return written


if __name__ == "__main__":
    print(main())
