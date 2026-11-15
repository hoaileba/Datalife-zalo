"""Registry of model-generated industries (gen/assets/industries_gen.json, written by gen.industry_gen).

One entry per industry key, the shape of new_industries.yaml plus what the hand-written trades get from code:
  {'meta': {shop_word, label, tet, orders, lines, lots?, visits?, decimal_units?, staff?, takeaway?},
   'items': [{name, group, unit, price, kind?, units?, sizes?, size_fmt?, size_step?}],
   'traits': {'service': bool, 'sizes': None|'word'|'paren', 'addon_group': str|None,
              'season': None|{'label', 'start': [m, d], 'end': [m, d]}},
   'unanswerable': [question templates with {P}], 'val': bool}

The rulebook sections a trade carries follow from its traits (sections()), so a generated trade gets its own measures
(gen.questions.allowed) and its own rulebook rows (gen.world_rules) with no per-trade code.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).with_name('assets') / 'industries_gen.json'


@lru_cache(maxsize=1)
def generated() -> dict:
    return json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {}


def reload():
    generated.cache_clear()


def is_generated(ind) -> bool:
    return ind in generated()


def meta(ind) -> dict:
    m = dict(generated()[ind]['meta'])
    m.setdefault('pre_tet', 1.2 if m['tet'] > 1 else 1.0)
    return m


def traits(ind) -> dict:
    return generated().get(ind, {}).get('traits', {})


def season_key(ind) -> str:
    return f'season_{ind}'


def sections(ind) -> set:
    """Rulebook section keys (gen.rulebook_gen.SECTIONS names, so gen.questions gates the same intents)."""
    if not is_generated(ind):
        return set()
    m, t = meta(ind), traits(ind)
    out = set()
    if m.get('lots'):
        out.add('expiry')
    if m.get('visits') == 'tables':
        out.add('tables')
    if m.get('visits') == 'plates':
        out.add('vehicles')
    if t.get('service'):
        out.add('service')
    if t.get('sizes') == 'word':
        out.add('size_word')
    if t.get('sizes') == 'paren':
        out.add('milk_tea')
    if m.get('decimal_units'):
        out.add('weighed')
    if t.get('addon_group'):
        out.add('addon')
    if t.get('season'):
        out.add('season')
    return out


def sizes(ind) -> list:
    """Size letters written on the items of a sized trade (the qty_size question draws one)."""
    out = []
    for e in generated()[ind]['items']:
        for s in e.get('sizes') or []:
            if s not in out:
                out.append(s)
    return out


def season_trade(key):
    """The generated trade a season key belongs to (None for other keys)."""
    ind = key[len('season_'):] if key.startswith('season_') else None
    return ind if ind and is_generated(ind) else None


def unanswerable(ind) -> list:
    return list(generated().get(ind, {}).get('unanswerable', []))


def catalog(ind) -> list:
    """Catalog entries in the gen.catalogs shape (sizes expanded)."""
    from .catalogs import _sized
    spec = generated()[ind]
    import re as _re
    return [dict(name=_re.sub(r'(?i)\bsize\s+size\b', 'size', n), group=e['group'], base_unit=e['unit'], price=float(p), cost=None,
                 kind=e.get('kind', 'goods'), units=[list(u) for u in e.get('units', [])])
            for e in spec['items'] for n, p in _sized(_unsized(e))]


def _unsized(e):
    """An item with sizes whose name already ends with a size: the size is written once."""
    if not e.get('sizes'):
        return e
    import re as _re
    return {**e, 'name': _re.sub(r'(?i)\s+(?:size\s+\S+|\([^)]{1,4}\))$', '', e['name'])}


def keys(val=None) -> list:
    """Generated trade keys; val=True only the held-out ones, False only the train ones."""
    return [k for k, v in generated().items() if val is None or bool(v.get('val')) == val]
