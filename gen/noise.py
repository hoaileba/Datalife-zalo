"""Per-shop presentation noise, drawn around the rates measured on the train files (docs/PLAN_TRAINDATA.md §1.1).

Every noise is decodable under rulebook §8/§10: a number keeps its value (each formatted cell is checked against the
production parser `datamate.values.parse_number`), a name variant only changes the writing (case, spaces, accents),
a status label is one synonym of exactly one of the four states, duplicates go only into tables written by order.

draw_noise(rng, level) -> Noise (the knobs); the helpers below format one cell given the knobs and an rng.
"""
from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from datamate.values import parse_number, parse_qty

# ---------------------------------------------------------------- vocabularies (harvested from train files)
STATUS_POOL = {
    'completed': ['Hoàn thành', 'Đã hoàn thành', 'Xong', 'xong', 'đã xong', 'đã lấy', 'Thành công', 'Đã giao', 'ok'],
    'cancelled': ['Đã hủy', 'Đã huỷ', 'hủy đơn', 'Đã hủy đơn', 'hủy', 'khách hủy', 'Không giao được'],
    'returned': ['Hoàn trả', 'Đổi trả', 'trả lại', 'Trả hàng', 'trả hàng', 'Đã trả hàng', 'hàng trả về', 'Đã hoàn hàng'],
    'delivering': ['Đang giao', 'Đang giao hàng', 'Chờ giao', 'đang gửi', 'Đang giao dịch', 'Đang xử lý'],
}
STATUS_EN = {'completed': ['completed'], 'cancelled': ['cancelled'], 'returned': ['returned'],
             'delivering': ['shipping']}
STATUS_EN2 = {'completed': ['Completed', 'Done', 'Paid'], 'cancelled': ['Cancelled', 'Voided'],
              'returned': ['Refunded', 'Returned'], 'delivering': ['Shipping', 'In transit']}
PAY_POOL = {'cash': ['Tiền mặt', 'TM'], 'transfer': ['Chuyển khoản', 'CK'], 'ewallet': ['Ví điện tử', 'Ví'],
            'cod': ['Thu hộ (COD)', 'COD'], 'debt': ['Ghi nợ', 'Nợ']}
PAY_EN = {'cash': 'cash', 'transfer': 'transfer', 'ewallet': 'ewallet', 'cod': 'cod', 'debt': 'debt'}
PAY_EN2 = {'cash': 'Cash', 'transfer': 'Bank transfer', 'ewallet': 'E-wallet', 'cod': 'COD', 'debt': 'On credit'}
WALKIN_POOL = ['Khách lẻ', 'khách lẻ', 'kl', 'lẻ']

MONEY_STYLES = ('int', 'float', 'str', 'comma', 'comma4', 'dot_d', 'k', 'tr', 'trdec')
DATE_STYLES = ('dmy', 'serial', 'thg', 'iso', 'date', 'noyear')


@dataclass
class Noise:
    level: str = 'normal'
    dup_rate: float = 0.02                 # duplicate line rows (tables written by order only)
    prod_variant_share: float = 0.15       # share of products whose name is sometimes written differently
    prod_variant_p: float = 0.5            # on those products, share of rows with a variant
    cust_variant_p: float = 0.1            # share of order rows with a spelling variant of the customer name
    phone_in_master: float = 0.4           # share of master-list customer names with the phone appended
    qty_unit_rate: float = 0.0             # share of quantity cells written '3 chai'
    serial_rate: float = 0.0               # share of date cells written as Excel serials (xlsx only)
    thg_rate: float = 0.0                  # share of date cells written '1 thg 6 2025'
    status_labels: dict = field(default_factory=dict)
    pay_labels: dict = field(default_factory=dict)
    walkin: list = field(default_factory=lambda: ['Khách lẻ'])
    money_mix: dict = field(default_factory=lambda: {'comma': 0.5, 'int': 0.5})
    fill_down: bool = False                # D: blank order cells on continuation lines
    verbosity: str = 'full'                # README level: full | partial | brief


def _pick(rng, seq):
    return seq[int(rng.integers(len(seq)))]


def draw_labels(rng, pool, two_share=0.5):
    """One or two synonyms per state (about half the shops mix two)."""
    out = {}
    for state, labels in pool.items():
        k = 2 if (len(labels) > 1 and rng.random() < two_share) else 1
        out[state] = [labels[i] for i in rng.choice(len(labels), size=k, replace=False)]
    return out


def draw_noise(rng, level='normal') -> Noise:
    """Knobs of one shop. level: 'clean' (almost none), 'normal' (train rates), 'heavy' (upper end)."""
    s = {'clean': 0.0, 'normal': 1.0, 'heavy': 1.6}[level]
    nz = Noise(level=level)
    nz.dup_rate = float(rng.uniform(0.01, 0.03)) * s * (rng.random() < 0.7)
    nz.prod_variant_share = float(rng.uniform(0.05, 0.45)) * min(s, 1.2)
    nz.prod_variant_p = float(rng.uniform(0.3, 0.6))
    nz.cust_variant_p = float(rng.uniform(0.0, 0.25)) * s
    nz.phone_in_master = float(rng.uniform(0.2, 0.5)) * min(s, 1.0)
    nz.qty_unit_rate = float(rng.uniform(0.35, 0.5)) * min(s, 1.0) * (rng.random() < 0.5)
    nz.serial_rate = float(rng.uniform(0.3, 0.6)) * min(s, 1.0) * (rng.random() < 0.45)
    nz.thg_rate = float(rng.uniform(0.2, 0.4)) * min(s, 1.0) * (rng.random() < 0.25)
    nz.status_labels = draw_labels(rng, STATUS_POOL, 0.5 if s else 0.0)
    nz.pay_labels = {k: [v[0]] if rng.random() < 0.8 else v for k, v in PAY_POOL.items()}
    nz.walkin = (list(WALKIN_POOL) if rng.random() < 0.25 * s else [_pick(rng, WALKIN_POOL[:2] + ['Khách lẻ'] * 3)])
    nz.money_mix = {'comma': 0.5, 'int': 0.5}
    nz.fill_down = bool(rng.random() < 0.5)
    nz.verbosity = _pick(rng, ['full', 'full', 'partial', 'brief'])
    return nz


# ---------------------------------------------------------------- numbers
def _thousands(n: int, sep=',') -> str:
    return f'{n:,}'.replace(',', sep)


def money_text(v, style):
    """v formatted in `style`, or None when that style cannot write v exactly."""
    if v is None:
        return None
    x = float(v)
    if not x.is_integer():
        return None if style not in ('float',) else x
    n = int(x)
    sign = '-' if n < 0 else ''
    a = abs(n)
    if style == 'int':
        return n
    if style == 'float':
        return float(n)
    if style == 'str':
        return str(n)
    if style == 'comma':
        return sign + _thousands(a)
    if style == 'comma4':
        return sign + _thousands(a) + '.0000'
    if style == 'dot_d':
        return sign + _thousands(a, '.') + 'đ'
    if style == 'k':
        return f'{sign}{a // 1000}k' if a % 1000 == 0 and a else None
    if style == 'tr':
        if a < 1_000_000 or a % 1000:
            return None
        m, rest = divmod(a, 1_000_000)
        rest //= 1000
        return f'{sign}{m}tr' + (f'{rest:03d}' if rest else '')
    if style == 'trdec':
        if a < 1_000_000 or a % 10_000:
            return None
        m, rest = divmod(a, 1_000_000)
        frac = f'{rest // 10_000:02d}'.rstrip('0')
        return f'{sign}{m},{frac}tr' if frac else f'{sign}{m}tr'
    raise ValueError(style)


def money(v, mix: dict, rng):
    """One money cell drawn from the style mixture; falls back to a plain number when the style cannot write v."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    styles, w = list(mix), np.array(list(mix.values()), dtype=float)
    style = styles[int(rng.choice(len(styles), p=w / w.sum()))]
    out = money_text(v, style)
    if out is None:
        out = money_text(v, 'int') if float(v).is_integer() else float(v)
    if isinstance(out, str) and parse_number(out) != float(v):      # never change a value
        out = money_text(v, 'int') if float(v).is_integer() else float(v)
    return out


def num(v):
    """A plain number cell (int when whole)."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    x = float(v)
    return int(x) if x.is_integer() else x


def qty(q, unit, rate, rng):
    """Quantity cell: '3 chai' with probability `rate` (and only when it parses back to (q, unit))."""
    q = num(q)
    if q is None or not unit or rng.random() >= rate:
        return q
    s = f'{q} {unit}'
    n, u = parse_qty(s)
    return s if (n == q and u == unit) else q


# ---------------------------------------------------------------- dates
SERIAL0 = dt.date(1899, 12, 30)


def date_text(d, style):
    """A date (or datetime) in one style: dmy '01/06/2025', thg '1 thg 6 2025', iso '2025-06-01', serial 45809,
    date (a real date cell), noyear '1/6' (only inside sheets named by month and year)."""
    if d is None:
        return None
    d0 = d.date() if isinstance(d, dt.datetime) else d
    if style == 'dmy':
        return d0.strftime('%d/%m/%Y')
    if style == 'thg':
        return f'{d0.day} thg {d0.month} {d0.year}'
    if style == 'iso':
        return d0.isoformat()
    if style == 'serial':
        return float((d0 - SERIAL0).days)
    if style == 'date':
        return d0
    if style == 'noyear':
        return f'{d0.day}/{d0.month}'
    if style == 'dmy_hm':
        return d.strftime('%d/%m/%Y %H:%M')
    if style == 'iso_dt':
        return d.strftime('%Y-%m-%d %H:%M:%S')
    raise ValueError(style)


def date_cell(d, base, nz: Noise, rng, xlsx=True, noyear_rate=0.0):
    """Base style most of the time; Excel serials / 'thg' / no-year mixed in by the shop's knobs. A serial is only
    used in xlsx and never for every cell of a column (the reader needs a full date nearby to type the column)."""
    r = rng.random()
    if xlsx and r < nz.serial_rate:
        return date_text(d, 'serial')
    r = rng.random()
    if r < nz.thg_rate:
        return date_text(d, 'thg')
    if noyear_rate and rng.random() < noyear_rate:
        return date_text(d, 'noyear')
    return date_text(d, base)


def to_py_datetime(t):
    if t is None or (isinstance(t, float) and t != t):
        return None
    try:
        import pandas as pd
        if pd.isna(t):
            return None
        return pd.Timestamp(t).to_pydatetime()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- names
def strip_accents(s: str) -> str:
    s = unicodedata.normalize('NFD', s).replace('đ', 'd').replace('Đ', 'D')
    return unicodedata.normalize('NFC', ''.join(c for c in s if unicodedata.category(c) != 'Mn'))


def _double_space(s: str, rng) -> str:
    parts = s.split(' ')
    if len(parts) < 2:
        return s
    k = int(rng.integers(len(parts) - 1))
    return ' '.join(parts[:k + 1]) + '  ' + ' '.join(parts[k + 1:])


def spelling_variants(name: str, rng, k=None):
    """1-3 writings of `name` that differ only in case, spaces or accents (rulebook §3: the same entity)."""
    kinds = ['upper', 'title', 'double', 'lower', 'noaccent']
    k = k or int(rng.integers(1, 4))
    out = []
    for kind in rng.choice(kinds, size=min(k, len(kinds)), replace=False):
        v = {'upper': name.upper(), 'title': name.title(), 'lower': name.lower(),
             'double': _double_space(name, rng), 'noaccent': strip_accents(name)}[str(kind)]
        if v != name and v not in out:
            out.append(v)
    return out or [name.upper()]


SURNAME_SWAP = {'Doãn': 'Đoàn', 'Đoàn': 'Doãn'}


def letter_variant(name: str):
    """Doãn<->Đoàn: a different spelling with different letters; only used where a code identifies the customer."""
    head, _, rest = name.partition(' ')
    return f'{SURNAME_SWAP[head]} {rest}' if head in SURNAME_SWAP and rest else None


def with_phone(name: str, phone, rng) -> str:
    if not phone or not isinstance(phone, str):
        return name
    p = phone.strip()
    style = int(rng.integers(3))
    if style == 0 and len(p) == 10:
        return f'{name} - {p[:4]} {p[4:7]} {p[7:]}'
    if style == 1:
        return f'{name} ({p})'
    return f'{name} {p}'


# ---------------------------------------------------------------- rows
def duplicate_rows(rows: list, rate: float, rng) -> tuple[list, int]:
    """Repeat ~rate of the rows right after themselves (an export glitch: identical rows of one order)."""
    if rate <= 0 or not rows:
        return rows, 0
    pick = rng.random(len(rows)) < rate
    out = []
    for r, p in zip(rows, pick):
        out.append(r)
        if p:
            out.append(list(r))
    return out, int(pick.sum())


def label(state, labels: dict, rng):
    opts = labels.get(state) or [state]
    return opts[0] if len(opts) == 1 else _pick(rng, opts)
