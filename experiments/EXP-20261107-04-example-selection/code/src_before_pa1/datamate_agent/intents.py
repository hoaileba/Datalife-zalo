from __future__ import annotations

import calendar
import re
from datetime import date

from .question_norm import normalize

MONTH_RANGE = re.compile(r"thang (\d{1,2})\s*/\s*(\d{4}) (?:den|toi)(?: het)? thang (\d{1,2})\s*/\s*(\d{4})")
MONTH_YEAR = re.compile(r"thang (\d{1,2})\s*(?:/|-|nam )\s*(\d{4})")
SHORT_QUARTER = re.compile(r"\bq ?([1-4])\s*(?:/|-|nam )\s*(\d{4})")
BARE_QUARTER = re.compile(r"\bquy ([1-4])\b(?!\s*(?:/|-|nam )\s*\d)")
BARE_MONTH = re.compile(r"\bthang (\d{1,2})\b(?!\s*(?:/|-|nam )\s*\d)")
MONTH_WORDS = {"muoi mot": 11, "muoi hai": 12, "gieng": 1, "chap": 12, "mot": 1, "hai": 2, "ba": 3, "tu": 4, "nam": 5, "bay": 7, "tam": 8, "chin": 9, "muoi": 10}
WORD_MONTH = re.compile(rf"\bthang ({'|'.join(MONTH_WORDS)})\b(?!\s*(?:nay|truoc|toi|\d))")
SAME_DAYS_LAST_MONTH = re.compile(r"cung ky thang truoc")
BEFORE_TET = re.compile(r"truoc tet")
BARE_MONTH_YEAR = re.compile(r"(?<![\d/])(\d{1,2})[-/](20\d{2})\b")
SHORT_MONTH_YEAR = re.compile(r"(?<![\d/.,])(1[0-2]|0?[1-9])/(2[4-9])\b(?![/\d])")
RANGE_DAYS = re.compile(r"tu (\d{1,2})/(\d{1,2})/(\d{4}) (?:den|toi)(?: het)?(?: ngay)? (\d{1,2})/(\d{1,2})/(\d{4})")
TET = re.compile(r"\btet(?: nam)? (20\d{2})\b")
QUARTER = re.compile(r"quy (\d)\s*(?:/|-|nam )\s*(\d{4})")
DAY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
LAST_N = re.compile(r"(\d+) ngay (?:gan nhat|gan day|vua qua|qua)")
ENTITY_MIN = 3


def _recent_year(month: int, as_of: date) -> int:
    """Tháng hay quý không ghi năm: của năm nay nếu không sau hôm nay, sau hôm nay thì của năm trước (rulebook)."""
    return as_of.year if month <= as_of.month else as_of.year - 1


def period_of(text: str, *, as_of: date | None = None) -> str | None:
    found = TET.search(text)
    if found:
        return f"clock.tet({found.group(1)})"
    found = RANGE_DAYS.search(text)
    if found:
        return f'clock.between("{found.group(3)}-{int(found.group(2)):02d}-{int(found.group(1)):02d}", "{found.group(6)}-{int(found.group(5)):02d}-{int(found.group(4)):02d}")'
    found = MONTH_RANGE.search(text)
    if found:
        first, last_month, last_year = int(found.group(1)), int(found.group(3)), int(found.group(4))
        return f'clock.between("{found.group(2)}-{first:02d}-01", "{last_year}-{last_month:02d}-{calendar.monthrange(last_year, last_month)[1]:02d}")'
    if re.search(r"(tu dau nam|nam nay)", text):
        return "clock.year_to_date()"
    found = LAST_N.search(text)
    if found:
        return f"clock.last_n_days({found.group(1)})"
    found = QUARTER.search(text) or SHORT_QUARTER.search(text)
    if found:
        return f"clock.quarter({int(found.group(1))}, {found.group(2)})"
    found = BARE_QUARTER.search(text)
    if found and as_of is not None:
        quarter = int(found.group(1))
        return f"clock.quarter({quarter}, {_recent_year(3 * quarter - 2, as_of)})"
    found = MONTH_YEAR.search(text) or BARE_MONTH_YEAR.search(text)
    if found:
        return f"clock.month({int(found.group(1))}, {found.group(2)})"
    found = SHORT_MONTH_YEAR.search(text)
    if found and not DAY.search(text):
        return f"clock.month({int(found.group(1))}, 20{found.group(2)})"
    found = DAY.search(text)
    if found:
        return f'clock.day("{found.group(3)}-{int(found.group(2)):02d}-{int(found.group(1)):02d}")'
    if as_of is not None:
        found = BARE_MONTH.search(text)
        month = int(found.group(1)) if found and 1 <= int(found.group(1)) <= 12 else None
        if month is None and (word := WORD_MONTH.search(text)):
            month = MONTH_WORDS[word.group(1)]
        if month is not None:
            return f"clock.month({month}, {_recent_year(month, as_of)})"
    if SAME_DAYS_LAST_MONTH.search(text):
        return "clock.this_month()"
    if "thang nay" in text:
        return "clock.this_month()"
    if re.search(r"thang truoc|thang roi", text):
        return "clock.last_month_full()"
    if "tuan nay" in text:
        return "clock.this_week()"
    if re.search(r"tuan truoc|tuan roi", text):
        return "clock.last_week()"
    if re.search(r"hom qua|bua qua", text):
        return "clock.yesterday()"
    if "hom nay" in text:
        return "clock.today()"
    return None


def baseline_of(text: str) -> str | None:
    """Kỳ đem ra so mà câu hỏi gọi bằng tên: cùng kỳ tháng trước, những ngày ngay trước Tết."""
    if SAME_DAYS_LAST_MONTH.search(text):
        return "clock.last_month_same_days()"
    tet = TET.search(text)
    if tet and BEFORE_TET.search(text):
        return f"clock.before_tet({tet.group(1)})"
    return None


def longest_match(text: str, names: dict[str, str]) -> str | None:
    best = None
    for key, name in names.items():
        if len(key) >= ENTITY_MIN and re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text) and (best is None or len(key) > len(best[0])):
            best = (key, name)
    return best[1] if best else None


def _quote(value: str) -> str:
    return repr(value)


def classify(question: str, entities: dict[str, dict[str, str]]) -> tuple[str, str, str] | None:
    """Trả (intent, answer_type, code) cho câu hỏi khớp mẫu, None nếu không khớp."""
    text = normalize(question)
    period = period_of(text)
    item = longest_match(text, entities["item"])
    group = longest_match(text, entities["group"])
    customer = longest_match(text, entities["customer"])
    staff = re.search(r"\bnv ?(\d{2,4})\b", text)
    ingredient = longest_match(text, entities["ingredient"])
    if period and re.search(r"\bhuy\b", text) and not re.search(r"ty le|%|phan tram", text) and re.search(r"don|bao nhieu|may", text):
        return "cancelled_orders", "number", f'cancelled_orders({period})'
    if period and re.search(r"ty le|%|phan tram", text) and re.search(r"\bhuy\b", text):
        return "cancel_rate", "percent", f"cancel_rate({period})"
    if period and re.search(r"khach", text) and re.search(r"(?:it nhat|tu|tren|≥) ?\d+ don", text) and re.search(r"%|phan tram|ty le", text):
        need = re.search(r"(?:it nhat|tu|tren|≥) ?(\d+) don", text).group(1)
        return "customers_share", "percent", f"round(100 * customer_count({period}, min_orders={need}) / customer_count({period}), 2)"
    days_over = re.search(r"(?:may|bao nhieu|so) ngay.*?(?:tu|dat|tren) ([\d.]{5,})", text)
    if period and days_over:
        raw = days_over.group(1).replace(".", "")
        op = ">" if re.search(r"\btren\b", text) else ">="
        return "days_over_revenue", "number", f'int((ranking(by="day", period={period}) {op} {raw}).sum())'
    if period and re.search(r"(khach|ai).*nhieu (don|lan)|(so don|nhieu don).*(khach|ai)|(khach|ai).*so don.*nhieu", text):
        return "top_customer_orders", "string", f'ranking(by="customer", metric="orders", period={period}).index[0]'
    if period and re.search(r"khong ban duoc|(hang|mat hang|san pham|mon)( nao)?( bi)? e\b", text):
        return "unsold_count", "number", f"unsold_count({period})"
    if re.search(r"gia tri.*(ton|kho)|hang (ton|du).*gia von|(ton|du).*tinh.*gia von", text):
        return "stock_value", "number", "stock_value()"
    if period and item and re.search(r"nhap tru|chenh.*nhap|nhap.*chenh", text):
        return "purchase_minus_sold", "number", f"purchase_minus_sold({period}, item={_quote(item)})"
    if item and re.search(r"chan.*le|nguyen.*le", text) and re.search(r"cuoi ngay|con|ton", text):
        return "stock_big", "list", f"stock_big(item={_quote(item)})"
    if period and re.search(r"ai mua.*nhieu tien|ai.*chi.*nhieu", text):
        return "top_customer_revenue", "string", f'ranking(by="customer", period={period}).index[0]'
    if period and re.search(r"nha cung cap|\bncc\b", text) and re.search(r"nhieu|cao nhat", text):
        return "top_supplier", "string", f"top_supplier({period})"
    shift_cmp = re.search(r"ca chieu", text) and re.search(r"ca sang", text)
    if period and shift_cmp and re.search(r"%|phan tram", text):
        metric = "order_count" if re.search(r"\bdon\b", text) and "doanh thu" not in text else "revenue"
        return "shift_compare", "percent", f'pct_change({metric}({period}, shift="chiều"), {metric}({period}, shift="sáng"))'
    if period and group and re.search(r"%|ty trong|phan tram|dong gop", text) and "khach" in text:
        return "customer_group_share", "percent", f"round(100 * revenue({period}, customer_group={_quote(group)}) / revenue({period}), 2)"
    if period and group and re.search(r"%|ty trong|phan tram|dong gop|phan cua", text):
        return "group_share", "percent", f"round(100 * revenue({period}, group={_quote(group)}) / revenue({period}), 2)"
    if period and re.search(r"ke don", text) and re.search(r"khong ke don|\bk ke don|\bko ke don", text):
        return "otc_revenue", "number", f"revenue({period}, prescription=False)"
    if period and re.search(r"ke don", text) and re.search(r"%|phan cua|ty le|ty trong|chiem", text):
        return "prescription_share", "percent", f"round(100 * revenue({period}, prescription=True) / revenue({period}), 2)"
    if period and re.search(r"(ty le).*huy|huy.*(ty le)", text):
        return "cancel_rate", "percent", f"cancel_rate({period})"
    if re.search(r"cung ky thang truoc", text) and "doanh thu" in text:
        return "revenue_vs_last_month", "percent", "pct_change(revenue(clock.this_month()), revenue(clock.last_month_same_days()))"
    all_months = [(int(m), int(y)) for m, y in re.findall(r"(?<![\d/])(\d{1,2})\s*(?:/|nam )\s*(20\d{2})", text)]
    ending = re.search(r"(\d) thang lien (?:nhau|tiep|tuc)? ?ket thuc o thang (\d{1,2})/(\d{4})", text)
    if ending and "doanh thu" in text:
        count, month, year = int(ending.group(1)), int(ending.group(2)), int(ending.group(3))
        spans = [((month - 1 - step) % 12 + 1, year + (month - 1 - step) // 12) for step in reversed(range(count))]
        return "revenue_months", "list", "[" + ", ".join(f"revenue(clock.month({m}, {y}))" for m, y in spans) + "]"
    if len(all_months) >= 2 and "doanh thu" in text and re.search(r"tang lien tuc|luon|giam lien tuc|lien tuc", text):
        first, last = all_months[0], all_months[-1]
        span = []
        y, m = first[1], first[0]
        while (y, m) <= (last[1], last[0]):
            span.append((m, y))
            m, y = (1, y + 1) if m == 12 else (m + 1, y)
        rising = "<" if not re.search(r"giam", text) else ">"
        values = ", ".join(f"revenue(clock.month({m}, {y}))" for m, y in span)
        if rising == ">":
            return "revenue_monotone", "boolean", f"increasing([{values}][::-1])"
        return "revenue_monotone", "boolean", f"increasing([{values}])"
    if len(all_months) >= 2 and "doanh thu" in text and re.search(r"cho toi|tung thang|moi thang|lan luot|tu thang", text) and not re.search(r"%|phan tram|nao", text):
        first, last = all_months[0], all_months[-1]
        span = []
        y, m = first[1], first[0]
        while (y, m) <= (last[1], last[0]):
            span.append((m, y))
            m, y = (1, y + 1) if m == 12 else (m + 1, y)
        return "revenue_months", "list", "[" + ", ".join(f"revenue(clock.month({m}, {y}))" for m, y in span) + "]"
    best_month = re.search(r"tu thang (\d{1,2})/(\d{4}) (?:toi|den) thang (\d{1,2})/(\d{4}) thang nao", text)
    if best_month:
        a, b, c, d = (int(best_month.group(i)) for i in range(1, 5))
        span = []
        y, m = b, a
        while (y, m) <= (d, c):
            span.append((m, y))
            m, y = (1, y + 1) if m == 12 else (m + 1, y)
        months_list = ", ".join(f"clock.month({m}, {y})" for m, y in span)
        return "best_month", "date", f"best_month([{months_list}])"
    if period and period.startswith("clock.month") and "doanh thu" in text and re.search(r"%|phan tram", text):
        match = re.search(r"clock\.month\((\d+), (\d+)\)", period)
        month, year = int(match.group(1)), int(match.group(2))
        if re.search(r"cung ky nam|nam truoc|nam ngoai", text) or (len(all_months) >= 2 and all_months[0][0] == all_months[1][0]):
            return "revenue_yoy", "percent", f"pct_change(revenue(clock.month({month}, {year})), revenue(clock.month({month}, {year - 1})))"
        if re.search(r"thang (lien )?truoc|thang lien ke|so voi thang", text):
            pm, py = (12, year - 1) if month == 1 else (month - 1, year)
            return "revenue_mom", "percent", f"pct_change(revenue(clock.month({month}, {year})), revenue(clock.month({pm}, {py})))"
    size = re.search(r"\bsize ([ml])\b", text)
    if period and size:
        return "size_quantity", "number", f'quantity({period}, size="{size.group(1).upper()}")'
    if re.search(r"lai gop", text) and period:
        if re.search(r"hang nao|mat hang nao|mon nao|san pham nao", text):
            return "best_profit_item", "string", f'ranking(by="item", metric="profit", period={period}).index[0]'
        return "gross_profit", "number", f"gross_profit({period}, item={_quote(item)})" if item else f"gross_profit({period})"
    if re.search(r"(lai rong|loi nhuan rong)", text) and period:
        return "net_profit", "number", f"net_profit({period})"
    count_items = re.search(r"mat hang.*?(?:o|trong) (?:≥ ?)?(\d+) don|(\d+) don khac nhau", text)
    if period and count_items and re.search(r"may|dem|bao nhieu", text):
        return "items_min_orders", "number", f"item_count({period}, min_orders={count_items.group(1) or count_items.group(2)})"
    count_customers = re.search(r"khach.*?(?:≥|it nhat|tu|tren) ?(\d+) don", text)
    if period and count_customers:
        return "customers_min_orders", "number", f"customer_count({period}, min_orders={count_customers.group(1)})"
    debt_day = re.search(r"(?:den het|het) (?:ngay )?(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if debt_day and re.search(r"\bno\b|cong no", text):
        iso = f"{debt_day.group(3)}-{int(debt_day.group(2)):02d}-{int(debt_day.group(1)):02d}"
        ages = re.search(r"(\d+)\D(\d+)(?: ngay)?,? (?:va )?(\d+)\D(\d+)(?: ngay)?,? (?:va |nhom )?(?:tren|hon|qua) (\d+)", text)
        if ages and "tuoi no" in text:
            a, b, c, d, e = (int(ages.group(index)) for index in range(1, 6))
            return "debt_aging", "list", f'[debt_aged("{iso}", {a}, {b}), debt_aged("{iso}", {c}, {d}), debt_aged("{iso}", {e + 1})]'
        over = re.search(r"(?:qua|hon|tren) (\d+) ngay", text)
        if over:
            return "debt_over_age", "number", f'debt_aged("{iso}", {int(over.group(1)) + 1})'
        top = re.search(r"(\d+) khach|top (\d+)", text)
        if top:
            n = top.group(1) or top.group(2)
            return "top_debtors", "table", f'(lambda s: {{"columns": ["khach_hang", "so_tien_no"], "rows": [[k, int(v)] for k, v in s.head({n}).items()]}})(debtors("{iso}"))'
        if re.search(r"khach", text) and re.search(r"(may|bao nhieu|so) khach|khach.*con (cong )?no", text) and not re.search(r"tien|tong cong", text):
            return "debtor_count", "number", f'debtor_count("{iso}")'
        return "debt_total", "number", f'debt_at("{iso}")'
    if period and re.search(r"khach.*(chi|mua|tien).*nhieu.*nhat|chi tieu nhieu nhat|tong tien mua cao nhat", text):
        top = re.search(r"(\d+) khach", text)
        if top:
            return "top_customers_revenue", "list", f'ranking(by="customer", period={period}).index[:{top.group(1)}].tolist()'
        return "top_customer_revenue", "string", f'ranking(by="customer", period={period}).index[0]'
    if period and re.search(r"ke don", text) and re.search(r"thu|tien|doanh thu", text) and not re.search(r"ty trong|chiem", text):
        return "prescription_revenue", "number", f"revenue({period}, prescription=True)"
    if period and re.search(r"ke don", text) and re.search(r"ty trong|chiem", text):
        return "prescription_share", "percent", f"round(100 * revenue({period}, prescription=True) / revenue({period}), 2)"
    if period and group and re.search(r"ty trong|chiem", text):
        return "group_share", "percent", f"round(100 * revenue({period}, group={_quote(group)}) / revenue({period}), 2)"
    if period and re.search(r"hoat chat", text) and ingredient:
        return "ingredient_revenue", "number", f"revenue({period}, ingredient={_quote(ingredient)})"
    months = re.search(r"(\d) thang lien tiep tu thang (\d{1,2})/(\d{4})", text)
    if months and "doanh thu" in text:
        count, month, year = int(months.group(1)), int(months.group(2)), int(months.group(3))
        spans = [((month - 1 + step) % 12 + 1, year + (month - 1 + step) // 12) for step in range(count)]
        return "revenue_months", "list", "[" + ", ".join(f"revenue(clock.month({m}, {y}))" for m, y in spans) + "]"
    if period and re.search(r"trung binh.*don|gia tri.*trung binh", text):
        return "average_order", "number", f"average_order({period})"
    threshold = re.search(r"(?:tu|dat|tren|it nhat|>=)\s*([\d.,]+)\s*(?:dong|d\b|k\b|nghin)?.*tro len|([\d.]{5,})\s*dong tro len", text)
    if period and threshold and "don" in text and "khach" not in text:
        raw = re.sub(r"[.,]", "", threshold.group(1) or threshold.group(2))
        return "orders_over_amount", "number", f'int((sold_orders({period})["revenue"] >= {raw}).sum())'
    repeat = re.search(r"khach.*(?:it nhat|tu|tren) (\d+) don|(?:it nhat|tu) (\d+) don.*khach", text)
    if period and repeat:
        return "customers_min_orders", "number", f"customer_count({period}, min_orders={repeat.group(1) or repeat.group(2)})"
    if period and re.search(r"khach.*nhieu (don|lan)|nhieu (don|lan).*khach", text):
        return "top_customer_orders", "string", f'ranking(by="customer", metric="orders", period={period}).index[0]'
    if period and re.search(r"ngay nao", text) and re.search(r"doanh thu|nhieu tien|dat nhat|cao nhat", text):
        return "best_day", "date", f'ranking(by="day", period={period}).index[0]'
    top = re.search(r"(?:liet ke |top |ke ten |neu |^|\s)(\d+) (?:mat hang|san pham|mon|hang)\b", text)
    if period and top:
        return "top_items", "list", f'ranking(by="item", metric="quantity", period={period}).index[:{top.group(1)}].tolist()'
    if period and re.search(r"(mat hang|san pham|mon|hang).*(chay|nhieu).*nhat|hot nhat", text):
        return "best_item", "string", f'ranking(by="item", metric="quantity", period={period}).index[0]'
    if period and re.search(r"phieu nhap|nhap hang", text) and re.search(r"tong|gia tri|tien", text):
        return "purchase_cost", "number", f"purchase_cost({period})"
    if period and re.search(r"gia nhap binh quan", text) and item:
        return "avg_purchase_price", "number", f"avg_purchase_price({period}, item={_quote(item)})"
    if period and re.search(r"khach tra no|thu.*no|tra no", text) and customer is None and "no them" not in text:
        return "debt_repaid", "number", f"debt_repaid({period})"
    if period and customer and re.search(r"no them", text):
        return "debt_customer", "list", f"[debt_added({period}, customer={_quote(customer)}), debt_repaid({period}, customer={_quote(customer)})]"
    debtors = re.search(r"den het ngay (\d{1,2})/(\d{1,2})/(\d{4}).*so khach con (cong )?no", text)
    if debtors:
        return "debtor_count", "number", f'debtor_count("{debtors.group(3)}-{int(debtors.group(2)):02d}-{int(debtors.group(1)):02d}")'
    if re.search(r"(trong kho|ton kho|cuoi ngay).*(con|bao nhieu)", text) and item:
        return "stock", "number", f"stock(item={_quote(item)})"
    price = DAY.search(text)
    if price and item and re.search(r"gia|don gia", text) and "tang gia" not in text:
        return "price_on_day", "number", f'sale_price({_quote(item)}, "{price.group(3)}-{int(price.group(2)):02d}-{int(price.group(1)):02d}")'
    window = re.search(r"(\d+) ngay", text)
    if price and item and window and re.search(r"tang gia|len|giam gia", text) and re.search(r"%|phan tram", text):
        return "price_effect", "percent", f'price_effect({_quote(item)}, "{price.group(3)}-{int(price.group(2)):02d}-{int(price.group(1)):02d}", days={window.group(1)})'
    if period and staff and re.search(r"ban duoc|doanh thu|tien", text):
        return "staff_revenue", "number", f'revenue({period}, staff="NV{staff.group(1).zfill(3)}")'
    shift = re.search(r"ca (sang|chieu)", text)
    if period and shift and re.search(r"doanh thu|tien", text):
        return "shift_revenue", "number", f'revenue({period}, shift="{"sáng" if shift.group(1) == "sang" else "chiều"}")'
    if period and shift and "don" in text:
        return "shift_orders", "number", f'order_count({period}, shift="{"sáng" if shift.group(1) == "sang" else "chiều"}")'
    if period and item and re.search(r"doanh thu|thu ve|tien ban|tien|bao nhieu tien", text) and not re.search(r"\bmay\b.*(ly|dia|chai|hop|goi)", text):
        return "item_revenue", "number", f"revenue({period}, item={_quote(item)})"
    if period and item and re.search(r"ban|so ", text):
        return "item_quantity", "number", f"quantity({period}, item={_quote(item)})"
    if period and group and "khach" in text and re.search(r"mua|tien|doanh thu", text):
        return "customer_group_revenue", "number", f"revenue({period}, customer_group={_quote(group)})"
    if period and group and re.search(r"doanh thu|tien", text):
        return "group_revenue", "number", f"revenue({period}, group={_quote(group)})"
    if period and re.search(r"(so|bao nhieu|may|nhieu) (don|bill)|(don|bill).*(bao nhieu|la may)", text):
        return "order_count", "number", f"order_count({period})"
    if period and re.search(r"doanh thu|revenue|ban duoc.*tien|thu ve", text):
        return "revenue", "number", f"revenue({period})"
    return None
