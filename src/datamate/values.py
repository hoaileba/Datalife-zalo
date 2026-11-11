"""Cell values: text normalization (nfc, fold), numbers (1.234.567 đ, 19tr990, 120k), quantities with a unit
("2 chai"), dates (ISO, d/m/y, Excel serials, Vietnamese "ngày 3 tháng 4 năm 2025").

Invariant: never guess beyond the text; unparsable -> None.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
import unicodedata
from decimal import Decimal
from functools import lru_cache


def nfc(s):
    return unicodedata.normalize('NFC', s) if isinstance(s, str) else s


def fold(s) -> str:
    """No accents, lower case, punctuation to spaces: for comparing labels and keywords."""
    try:
        return _fold_cached(s)
    except TypeError:
        return _fold(s)


@lru_cache(maxsize=1 << 18, typed=True)
def _fold_cached(s) -> str:
    return _fold(s)


def _fold(s) -> str:
    s = unicodedata.normalize('NFD', nfc(str(s))).replace('đ', 'd').replace('Đ', 'D')
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)          # CamelCase -> Camel Case
    s = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', s)     # SLQuyDoi -> SL Quy Doi
    s = re.sub(r'[_\-/().,:]+', ' ', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


@lru_cache(maxsize=1 << 16)
def _shape_text(s: str) -> frozenset:
    return frozenset('a' if c.isalpha() else '9' if c.isdigit() else ' ' if c.isspace() else c for c in s)


def shape(v):
    """What a cell is made of, for telling a record from a heading: the set of letter/digit/space/punctuation classes
    of a text ("KH001" -> {a, 9}; "Nhóm: Bia" -> {a, ' ', ':'}), or the kind of a non-text value."""
    return _shape_text(v.strip()) if isinstance(v, str) else type(v).__name__


# ---------------------------------------------------------------- numbers and quantities
_CURRENCY = re.compile(r'\s*(vnđ|vnd|đồng|đ|₫|d)\s*$', re.I)


def _plain_number(s: str, decimal=None):
    """'1.234.567' / '1,234,567' / '1.5' / '1,5'. A group of exactly 3 digits after one separator is thousands,
    unless `decimal` (the column's own decimal mark, see data.decimal_mark) says that separator is the decimal mark."""
    s = s.replace(' ', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?[\d.,]*\d', s) or s.lstrip('+-')[:1] in '.,' and len(re.findall(r'[.,]', s)) > 1:
        return None                                     # '.5' and ',5' are halves; '.5.0' is nothing
    negative = s.startswith('-')
    s = s.lstrip('+-')
    seps = re.findall(r'[.,]', s)
    if not seps:
        v = float(s)
    elif len(set(seps)) == 2:                            # both: the last one is the decimal mark
        last = max(s.rfind('.'), s.rfind(','))
        v = float(re.sub(r'[.,]', '', s[:last]) + '.' + s[last + 1:])
    else:
        parts = s.split(seps[0])
        if decimal == seps[0] and len(parts) == 2:
            v = float(parts[0] + '.' + parts[1])
        elif len(parts) > 2 or decimal not in (None, seps[0]) or (len(parts) == 2 and len(parts[1]) == 3 and parts[0] != '0'):
            if not all(len(p) == 3 for p in parts[1:]):
                return None
            v = float(''.join(parts))
        else:
            v = float(parts[0] + '.' + parts[1])
    return -v if negative else v


def parse_number(v, decimal=None):
    try:
        return _parse_number_cached(v, decimal)
    except TypeError:
        return _parse_number(v, decimal)


@lru_cache(maxsize=1 << 18, typed=True)
def _parse_number_cached(v, decimal):
    return _parse_number(v, decimal)


LONG = 120         # longer text is never a number, quantity or date (and the regexes stay linear)


def _parse_number(v, decimal=None):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str) or len(v.strip()) > LONG:
        return None
    s = re.sub(r'^[−–]', '-', nfc(v).strip().lower())        # unicode minus / en dash as a sign
    s = '-' + s[:-1].strip() if re.fullmatch(r'[\d.,\s]+-', s) else s                 # accounting '5.000-'
    negative = s.startswith('(') and s.endswith(')')
    s = _CURRENCY.sub('', s.strip('()').strip())
    m = re.fullmatch(r'([+-]?\d+(?:[.,]\d+)?)\s*(tr|triệu|trieu)\s*(\d{1,3})?', s)       # 19tr990, 1,5 triệu
    if m:
        base = Decimal(m[1].replace(',', '.'))                                              # exact: 1,047tr = 1047000
        x = float(abs(base) * 1000000 + (int(m[3].ljust(3, '0')) * 1000 if m[3] else 0))
        x = -x if base < 0 or m[1].startswith('-') else x
        return -x if negative else x
    m = re.fullmatch(r'([+-]?\d+(?:[.,]\d+)?)\s*(k|nghìn|nghin|ngàn|ngan)', s)              # 120k
    if m:
        x = float(Decimal(m[1].replace(',', '.')) * 1000)
        return -x if negative else x
    x = _plain_number(s, decimal)
    return None if x is None else (-x if negative else x)


QTY_RE = re.compile(r'^\s*([+-]?\d+(?:[.,]\d+)?)\s*([^\d\s=(,;][^=(,;]*?)?\s*([=(,;].*)?$')


def parse_qty(v, decimal=None):
    """'2 chai' -> (2, 'chai'); '1 thùng = 24 lon' -> (1, 'thùng'); plain number -> (n, None)."""
    if v is None or isinstance(v, bool):
        return None, None
    if isinstance(v, (int, float)):
        return float(v), None
    s = nfc(str(v)).strip()
    if len(s) > LONG:
        return None, None
    n = parse_number(s, decimal)
    if n is not None:
        return n, None
    m = QTY_RE.match(s)
    if not m or not m[2] or not m[2][0].islower():
        return None, None
    n = parse_number(m[1], decimal)
    return (None, None) if n is None else (n, re.sub(r'\s+', ' ', m[2]).strip())


MULTIPLIER = re.compile(r'\d\s*(k|tr|triệu|trieu|nghìn|nghin|ngàn|ngan)\b')        # 120k, 1,5tr: exact already


def decimal_mark(values):
    """The decimal mark a number column itself proves, or None (then "1.250" / "1,250" read as thousands). Proof that
    a mark is decimal: "0.500" (a thousands group never follows a lone 0), "1.234,5" (the last of two marks), or
    two or more short decimals ("0,5", "1,25"), at least as many as the ambiguous "d,ddd" values. Seeing the other mark group
    thousands ("1.250.000") proves nothing about "35,000"; a mark also used to group thousands is never decimal."""
    proof, short, ambiguous, grp = Counter(), Counter(), Counter(), Counter()
    for v in set(v for v in values if isinstance(v, str)):
        t = re.sub(r'[^\d.,]', '', v) if not MULTIPLIER.search(v.lower()) else ''
        seps = re.findall(r'[.,]', t.strip('.,'))
        if len(set(seps)) == 2:
            last = t[max(t.rfind('.'), t.rfind(','))]
            proof[last] += 1
            grp[',' if last == '.' else '.'] += 1
        elif len(seps) > 1:
            grp[seps[0]] += 1
        elif seps:
            head, tail = t.strip('.,').split(seps[0])
            (short if len(tail) != 3 else proof if head in ('', '0') else ambiguous)[seps[0]] += 1
    for mark, other in (('.', ','), (',', '.')):
        if not grp[mark] and not (proof[other] or short[other]) and (proof[mark] or short[mark] >= max(2, ambiguous[mark])):
            return mark
    return None


# ---------------------------------------------------------------- dates
SERIAL0 = dt.datetime(1899, 12, 30)


def _mk(y, mo, d, h=0, mi=0, se=0):
    try:
        return dt.datetime(y + (2000 if y < 30 else 1900) if y < 100 else y, mo, d, h, mi, se)      # Excel's pivot: 29 -> 2029, 84 -> 1984
    except ValueError:
        return None


def parse_datetime(v, year_hint=None, serial_ok=True, dayfirst=True, serials=(36500, 47500)):
    """dayfirst=False reads d/m/y text as m/d/y (a column whose cells prove it, see columns.date_order). Excel serials
    count in `serials` (2000-2030; a date header widens it to 1949-2099, for birthdays)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day)
    if isinstance(v, (int, float)):
        return SERIAL0 + dt.timedelta(seconds=round(float(v) * 86400)) if serial_ok and serials[0] <= v <= serials[1] else None
    s = nfc(str(v)).strip().lower()
    if len(s) > LONG:
        return None
    m = re.fullmatch(r'(\d{4})([-/.])(\d{1,2})\2(\d{1,2})(?:[ t](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?', s)
    if m:
        return _mk(int(m[1]), int(m[3]), int(m[4]), int(m[5] or 0), int(m[6] or 0), int(m[7] or 0))   # year first: 2025/02/01
    d, mo = (1, 2) if dayfirst else (2, 1)
    m = re.fullmatch(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:,?\s+(\d{1,2})[:h](\d{2})(?::(\d{2}))?)?', s)
    if m:
        return _mk(int(m[3]), int(m[mo]), int(m[d]), int(m[4] or 0), int(m[5] or 0), int(m[6] or 0))
    m = re.fullmatch(r'(\d{1,2})[:h](\d{2})(?::(\d{2}))?\s+(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})', s)
    if m:
        return _mk(int(m[6]), int(m[mo + 3]), int(m[d + 3]), int(m[1]), int(m[2]), int(m[3] or 0))
    m = re.fullmatch(r'(?:ngày\s*)?(\d{1,2})\s*(?:thg|tháng|th)\s*(\d{1,2})[\s,/]*(?:năm\s*)?(\d{4})', s)
    if m:
        return _mk(int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r'(\d{1,2})[/\-.](\d{1,2})', s)
    if m and year_hint:
        return _mk(year_hint, int(m[mo]), int(m[d]))
    if serial_ok and re.fullmatch(r'\d{5}(\.0+)?', s):
        return parse_datetime(float(s), year_hint, serial_ok, dayfirst, serials)
    return None


def year_hint(src: str):
    m = re.search(r'(20\d{2})', src)
    return int(m[1]) if m else None


