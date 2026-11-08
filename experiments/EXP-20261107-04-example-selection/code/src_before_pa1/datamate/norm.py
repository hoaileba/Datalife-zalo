from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Iterable

EXCEL_EPOCH = datetime(1899, 12, 30)
EXCEL_SERIAL_MIN = 20000
EXCEL_SERIAL_MAX = 80000

VN_MONTH_WORDS = ("thg", "thang", "tháng")

_SUFFIX_MULT = (
    ("triệu", 1_000_000),
    ("trieu", 1_000_000),
    ("tr", 1_000_000),
    ("nghìn", 1_000),
    ("nghin", 1_000),
    ("ngàn", 1_000),
    ("ngan", 1_000),
    ("k", 1_000),
)

_CURRENCY_TOKENS = ("vnđ", "vnd", "đồng", "dong", "₫", "đ", "d")

_WS = re.compile(r"\s+")
_NUM_CORE = re.compile(r"-?[\d.,\s]+")


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def squeeze(value: Any) -> str:
    if is_blank(value):
        return ""
    text = unicodedata.normalize("NFC", str(value))
    return _WS.sub(" ", text).strip()


def name_key(value: Any) -> str:
    return squeeze(value).casefold()


def fold_key(value: Any) -> str:
    """Khoá so khớp tên bỏ dấu tiếng Việt: chỉ dùng để KHỚP, đáp án vẫn lấy tên nguyên văn."""
    text = unicodedata.normalize("NFD", name_key(value))
    stripped = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    stripped = stripped.replace("\u0111", "d").replace("\u0110", "d")
    return unicodedata.normalize("NFC", stripped)


def accent_count(text: str) -> int:
    return sum(1 for char in text if char in "\u0111\u0110" or unicodedata.normalize("NFD", char) != char)


def display_name(cells: Iterable[Any], official: frozenset[str] = frozenset()) -> str:
    """C\u00e1ch ghi \u0111\u01b0a v\u00e0o \u0111\u00e1p \u00e1n khi m\u1ed9t t\u00ean c\u00f3 nhi\u1ec1u c\u00e1ch ghi: t\u00ean \u1edf danh m\u1ee5c, r\u1ed3i c\u00e1ch ghi c\u00f3 d\u1ea5u, r\u1ed3i ghi nhi\u1ec1u nh\u1ea5t."""
    counts = Counter(str(cell) for cell in cells if not is_blank(cell))
    return max(counts, key=lambda name: (name in official, accent_count(name), counts[name]))


def _strip_currency(text: str) -> tuple[str, int]:
    low = text.casefold().strip()
    mult = 1
    changed = True
    while changed:
        changed = False
        for token in _CURRENCY_TOKENS:
            if low.endswith(token) and len(low) > len(token):
                head = low[: -len(token)].strip()
                if head and (head[-1].isdigit() or head[-1] in ".,) "):
                    low = head
                    changed = True
                    break
    for suffix, factor in _SUFFIX_MULT:
        if low.endswith(suffix) and len(low) > len(suffix):
            head = low[: -len(suffix)].strip()
            if head and head[-1].isdigit():
                low = head
                mult = factor
                break
    return low, mult


_MILLION_PAIR = re.compile(r"^(-?\d+)\s*(?:tr|trieu|triệu)\s*(\d{1,3})$")


def _million_pair(text: str) -> float | None:
    match = _MILLION_PAIR.match(text.strip())
    if match is None:
        return None
    whole = int(match.group(1))
    tail = match.group(2)
    fraction = int(tail) * (10 ** (3 - len(tail))) if len(tail) == 3 else int(tail) / (10 ** len(tail)) * 1000
    magnitude = abs(whole) * 1_000_000 + fraction * 1_000
    return -magnitude if whole < 0 or text.strip().startswith("-") else magnitude


def _digits_to_float(core: str, *, force_decimal: bool = False) -> float:
    core = core.replace(" ", "").replace(" ", "")
    neg = core.startswith("-")
    if neg:
        core = core[1:]
    has_dot = "." in core
    has_comma = "," in core
    if has_dot and has_comma:
        dec = "," if core.rfind(",") > core.rfind(".") else "."
        thou = "." if dec == "," else ","
        core = core.replace(thou, "").replace(dec, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        parts = core.split(sep)
        tail = parts[-1]
        if force_decimal and len(parts) == 2:
            core = core.replace(sep, ".")
        elif len(parts) > 2 or len(tail) == 3:
            core = core.replace(sep, "")
        elif len(tail) in (1, 2):
            core = core.replace(sep, ".")
        else:
            core = core.replace(sep, "")
    if core == "":
        raise ValueError("empty numeric core")
    value = float(core)
    return -value if neg else value


def parse_number(value: Any, *, default: float | None = None) -> float | None:
    """Số lượng, hệ số, tỉ lệ: ưu tiên đọc dấu phân cách đơn là dấu thập phân."""
    if is_blank(value):
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = squeeze(value)
    paren = text.startswith("(") and text.endswith(")")
    if paren:
        text = text[1:-1].strip()
    low, mult = _strip_currency(text)
    match = _NUM_CORE.search(low)
    if match is None:
        return default
    try:
        out = _digits_to_float(match.group(0)) * mult
    except ValueError:
        return default
    return -out if paren else out


def parse_money(value: Any, *, default: int | None = None) -> int | None:
    """Tiền VND: dấu phân cách đơn với 3 chữ số sau coi là ngăn nghìn."""
    if is_blank(value):
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return round_money(float(value))
    text = squeeze(value)
    paren = text.startswith("(") and text.endswith(")")
    if paren:
        text = text[1:-1].strip()
    low, mult = _strip_currency(text)
    paired = _million_pair(low) if mult == 1 else None
    if paired is None:
        paired = _million_pair(text.casefold())
    if paired is not None:
        return round_money(-paired if paren else paired)
    match = _NUM_CORE.search(low)
    if match is None:
        return default
    try:
        out = _digits_to_float(match.group(0), force_decimal=mult >= 1_000_000) * mult
    except ValueError:
        return default
    out = -out if paren else out
    return round_money(out)


def round_money(value: float) -> int:
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def round2(value: float) -> float:
    scaled = value * 100.0
    rounded = math.floor(scaled + 0.5) if scaled >= 0 else -math.floor(-scaled + 0.5)
    return rounded / 100.0


def _from_serial(serial: float) -> datetime:
    return EXCEL_EPOCH + timedelta(days=float(serial))


def parse_datetime(value: Any, *, default: datetime | None = None) -> datetime | None:
    if is_blank(value):
        return default
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if EXCEL_SERIAL_MIN <= float(value) <= EXCEL_SERIAL_MAX:
            return _from_serial(value)
        return default
    text = squeeze(value)
    if text == "":
        return default
    if re.fullmatch(r"\d{4,6}(\.\d+)?", text):
        serial = float(text)
        if EXCEL_SERIAL_MIN <= serial <= EXCEL_SERIAL_MAX:
            return _from_serial(serial)
    low = text.casefold()
    low = re.sub(r"\b(ngày|ngay)\b", " ", low)
    low = re.sub(r"\b(năm|nam)\b", " ", low)
    for word in VN_MONTH_WORDS:
        low = re.sub(rf"\b{word}\b", "/", low)
    low = _WS.sub(" ", low).strip()
    low = low.replace(" /", "/").replace("/ ", "/")
    hour = minute = second = 0
    time_match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", low)
    if time_match is not None:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        second = int(time_match.group(3) or 0)
        low = (low[: time_match.start()] + " " + low[time_match.end() :]).strip()
    low = low.replace("-", "/").replace(".", "/")
    low = _WS.sub(" ", low).strip().strip("/").strip()
    low = re.sub(r"\s+", "/", low)
    low = re.sub(r"/+", "/", low)
    parts = [p for p in low.split("/") if p != ""]
    if len(parts) < 3:
        return default
    try:
        if len(parts[0]) == 4:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return default
    if year < 100:
        year += 2000
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100):
        return default
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return default


def parse_date(value: Any, *, default: date | None = None) -> date | None:
    moment = parse_datetime(value)
    return moment.date() if moment is not None else default


def parse_bool_vn(value: Any, *, default: bool | None = None) -> bool | None:
    if is_blank(value):
        return default
    if isinstance(value, bool):
        return value
    text = name_key(value)
    if text in {"1", "true", "x", "co", "có", "yes", "y", "đúng", "dung", "roi", "rồi"}:
        return True
    if text in {"0", "false", "khong", "không", "no", "n", "sai", "chua", "chưa"}:
        return False
    return default
