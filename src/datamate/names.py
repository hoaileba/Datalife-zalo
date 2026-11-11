"""dm.name_key: one key per name written several ways, for grouping and joining names when there is no code.

Same name: case, spaces and punctuation differ, or an unaccented spelling ("Bach Duy Giang") next to its ONE accented
form ("Bạch Duy Giang"). Different names: different accents ("Bạch" / "Bách"), or an unaccented spelling that matches
several accented forms (kept as written, never guessed).
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from .values import fold


def _spelled(v):
    """Case, spaces and punctuation folded; accents kept."""
    return ' '.join(re.sub(r'[\W_]+', ' ', unicodedata.normalize('NFC', str(v)).casefold()).split())


def name_key(values, *others):
    """Keys for `values`; `others` (e.g. the master list's names) also count when finding an unaccented spelling's
    accented form. Join two tables on name_key(a, b) and name_key(b, a)."""
    s = values if isinstance(values, pd.Series) else pd.Series(list(values))
    pool = pd.concat([s, *(pd.Series(list(o)) for o in others)]).dropna().unique()
    keys = {v: _spelled(v) for v in pool}
    accented = {}
    for k in set(keys.values()):
        if fold(k) != k:
            accented.setdefault(fold(k), set()).add(k)
    def one(v):
        k = keys.get(v) or _spelled(v)
        forms = accented.get(k, ())
        return next(iter(forms)) if fold(k) == k and len(forms) == 1 else k
    return s.map(lambda v: one(v) if pd.notna(v) else '')
