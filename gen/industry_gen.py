"""Model-generated industries for the unique-world data (docs/PLAN_UNIQUE_WORLDS.md step 1).

The code draws what each trade must have (its traits: lots, service lines, sizes, weighed goods, add-ons, tables or
vehicles, a named season) and a sector hint, so the trait mix is controlled; DeepSeek (thinking off, JSON) invents
the trade itself: name, items with real Vietnamese names, groups, units, prices, the season dates. Every reply is
checked (schema, counts the traits need, prices, units, unique names, not a trade we already have); a failed check
goes back to the model once with the problems, then the trade is skipped.

  PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
  $PY -m gen.industry_gen --n 300 --workers 8 --config config.deepseek_direct_nothink.yaml --yes
  $PY -m gen.industry_gen --dry-run --n 3          # prints the recipes and one prompt, no model call

Output: gen/assets/industries_gen.json (gen.industries reads it), appended to and saved after every trade;
gen/assets/industries_gen.log.jsonl: every call (usage, problems).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from gen import industries  # noqa: E402

LOG = industries.PATH.with_name('industries_gen.log.jsonl')
PRICES = (0.28, 0.028, 0.42)          # USD per 1M tokens: input miss, input hit, output (DeepSeek flash)

SECTORS = [
    'ăn uống mang đi', 'đồ uống', 'bánh và đồ ngọt', 'nông sản tươi', 'thực phẩm khô và đặc sản vùng miền',
    'đồ gia dụng', 'điện máy nhỏ', 'đồ điện và chiếu sáng', 'kim khí và dụng cụ', 'nội thất và trang trí',
    'chăn ga gối nệm', 'vải và đồ may', 'giày dép và túi', 'phụ kiện thời trang', 'trang sức và đồng hồ',
    'đồ chơi trẻ em', 'sách và văn hoá phẩm', 'nhạc cụ', 'thể thao và dã ngoại', 'xe đạp', 'phụ tùng ô tô',
    'hoa và cây cảnh', 'thú y và thức ăn chăn nuôi', 'thuỷ sản và ngư cụ', 'thiết bị y tế gia đình',
    'chăm sóc cá nhân', 'đồ cúng và hàng mã', 'đồ cưới và tiệc', 'in ấn và quà tặng', 'máy tính và linh kiện',
    'camera và thiết bị an ninh', 'đồ dùng văn phòng', 'bao bì và vật tư đóng gói', 'hoá chất tẩy rửa',
    'đồ nhựa', 'gốm sứ và thủy tinh', 'đồ thờ và đồ gỗ', 'dụng cụ làm bánh', 'trà và cà phê hạt', 'rượu và bia',
    'dịch vụ giặt ủi', 'dịch vụ sửa chữa đồ gia dụng', 'dịch vụ chăm sóc xe', 'dịch vụ làm đẹp', 'phòng tập',
    'dịch vụ cho thú cưng', 'karaoke và giải trí', 'quán ăn có bàn', 'quán nướng và bia', 'chợ đầu mối nhỏ',
]

TRAIT_WEIGHTS = {             # chance of each trait in a recipe (several may hold; the prompt names them)
    'lots': 0.25, 'service': 0.25, 'sizes': 0.2, 'weighed': 0.15, 'addon': 0.12, 'season': 0.35,
}


def recipe(rng: random.Random) -> dict:
    """What one trade must have. Tables (restaurant-like) and plates (vehicle service) are exclusive visit kinds."""
    r = {'sector': rng.choice(SECTORS)}
    visits = rng.choices([None, 'tables', 'plates'], [0.8, 0.12, 0.08])[0]
    r['visits'] = visits
    for t, p in TRAIT_WEIGHTS.items():
        r[t] = rng.random() < p
    if visits == 'plates':
        r['service'] = True
    if r['sizes']:
        r['sizes'] = rng.choice(['word', 'paren'])
    if visits == 'tables' and rng.random() < 0.5:
        r['addon'] = True
    if r['weighed'] and r['sizes']:
        r['sizes'] = False
    return r


SYSTEM = """You design one realistic small Vietnamese shop trade (ngành hàng) for synthetic sales data. Reply with ONE JSON object only.

Keys:
- "key": short ascii snake_case id of the trade (e.g. "bike_shop")
- "label": the trade in Vietnamese, lower case, 2-5 words (e.g. "xe đạp thể thao")
- "shop_word": how people call the shop: one of "cửa hàng", "tiệm", "quán", "shop", "đại lý", "nhà sách", "xưởng", "cơ sở"
- "tet": sales multiplier during Tết (0.3 = mostly closed ... 2.5 = peak season)
- "orders": [min, max] orders per day of a small shop (between 8 and 180)
- "lines": mean item lines per order (1.2 to 4.5)
- "staff": staff count (2 to 6)
- "items": 22 to 32 products/services the shop sells, each {"name", "group", "unit", "price", "kind", "units"?, "sizes"?}
    name: the real Vietnamese name a shop writes on its list, with brand/spec when natural; every name different
    group: product group in Vietnamese lower case (4 to 8 different groups in the shop)
    unit: base unit word (cái, chai, hộp, gói, kg, bộ, lần, suất, ly, phần, cuộn, mét, ...)
    price: price in VND of ONE base unit, an integer, realistic for Vietnam in 2026
    kind: "goods" (bought and resold) or "made" (prepared or performed on the spot: dishes, drinks, services)
    units (goods only, optional): larger packs [[unit, how many base units], ...], e.g. [["thùng", 24]]; about a third of the goods
    sizes (only when asked below): list of size letters for that item
- never items for delivery/shipping, fees, deposits, vouchers or discounts (the data keeps those apart)
- "unanswerable": 3 short questions an owner of this trade might ask that sales/stock/debt data cannot answer (customer feelings, weather, staff skill...), Vietnamese, each may contain "{P}" for a period

Requirements for THIS trade are given by the user. Follow them exactly; invent everything else from real knowledge of the trade."""


def user_prompt(r: dict, avoid: list) -> str:
    need = [f'Sector to start from: {r["sector"]} (pick a specific trade inside it).']
    if r['visits'] == 'tables':
        need.append('Customers sit at tables (a restaurant-like trade): most items are "made" dishes or drinks.')
    if r['visits'] == 'plates':
        need.append('Customers bring a vehicle (motorbike, car, bicycle, e-bike...) for service: a service/repair trade.')
    if r['service']:
        need.append('At least 5 items are services: their group starts with the words "dịch vụ" (e.g. "dịch vụ vệ sinh"), '
                    'kind "made", unit "lần" or similar. The other items are goods or parts sold.')
    if r['lots']:
        need.append('Goods have expiry dates (sold by lot); at least 15 items are "goods".')
    if r['sizes'] == 'word':
        need.append('At least 4 items come in sizes written as words after "size": give them "sizes" like ["S", "M", "L"] '
                    'or ["36", "37", "38"] (2 to 5 sizes each).')
    if r['sizes'] == 'paren':
        need.append('At least 4 items come in two or three sizes written in brackets: give them "sizes" like ["M", "L"] or ["S", "M", "L"].')
    if r['weighed']:
        need.append('At least 5 goods are sold by weight: unit "kg", price per kg.')
    if r['addon']:
        need.append('Add "addon_group": the Vietnamese group name of small add-ons sold with the main items (like toppings or '
                    'extra sauce), and at least 3 items of that group with kind "addon" and a small price.')
    if r['season']:
        need.append('Add "season": the trade\'s busy season with a Vietnamese name, as {"label": "mùa ...", "start": [month, day], '
                    '"end": [month, day]} (40 to 120 days long; it may cross the new year).')
    need.append('Do NOT make any of these existing trades or a near copy of one: ' + '; '.join(avoid) + '.')
    return '\n'.join(need)


# ---------------------------------------------------------------- checks
# items named like a concept the ledger keeps apart (delivery trips and fees, deposits, vouchers, discounts): the
# oracle answers those questions from their own fields (or as unanswerable), so such an item would make the gold
# ambiguous ('số chuyến giao hàng' counted from a "giao hàng nội thành" line)
CONCEPT_ITEM = re.compile(r'\b(giao hang|van chuyen|ship|shipping|phi giao|phi ship|phi phuc vu|phu thu|thue vat|dat coc|tien coc|'
                          r'voucher|chiet khau|hoan tien)\b|\bgiao\b.*\btan (nha|noi)\b')


def concept_item(e) -> bool:
    return bool(CONCEPT_ITEM.search(_fold(str(e.get('name', '')))) or CONCEPT_ITEM.search(_fold(str(e.get('group', '')))))


def _fold(s: str) -> str:
    s = unicodedata.normalize('NFD', s.lower().replace('đ', 'd'))
    return re.sub(r'\s+', ' ', ''.join(c for c in s if unicodedata.category(c) != 'Mn')).strip()


def existing_labels() -> dict:
    """fold(label) -> label of every trade we already have (train, hand-written, generated)."""
    import yaml
    from gen.sim import TRAIN_META
    out = {_fold(m['label']): m['label'] for k, m in TRAIN_META.items()}
    new = yaml.safe_load((industries.PATH.with_name('new_industries.yaml')).read_text(encoding='utf-8'))
    out.update({_fold(v['meta']['label']): v['meta']['label'] for k, v in new.items()})
    out.update({_fold(v['meta']['label']): v['meta']['label'] for k, v in industries.generated().items()})
    return out


def check(d: dict, r: dict, taken: dict, keys: set) -> list:
    """Problems of one reply (empty = accepted)."""
    p = []
    for k in ('key', 'label', 'shop_word', 'tet', 'orders', 'lines', 'items', 'unanswerable'):
        if k not in d:
            p.append(f'missing key "{k}"')
    if p:
        return p
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,30}', str(d['key'])):
        p.append('key must be ascii snake_case')
    if _fold(d['label']) in taken or d['key'] in keys:
        p.append(f'trade "{d["label"]}" already exists: invent another one')
    items = d['items']
    if not isinstance(items, list) or not 20 <= len(items) <= 40:
        return p + ['items: give 22 to 32 items']
    names = [_fold(str(e.get('name', ''))) for e in items]
    if len(set(names)) != len(names):
        p.append('two items share one name')
    groups = {e.get('group') for e in items}
    if not 3 <= len(groups) <= 10:
        p.append('use 4 to 8 different groups')
    for e in items:
        n = e.get('name', '?')
        if not isinstance(e.get('price'), (int, float)) or not 500 <= e['price'] <= 200_000_000:
            p.append(f'{n}: price must be an integer VND between 500 and 200000000')
        if e.get('kind') not in ('goods', 'made', 'addon'):
            p.append(f'{n}: kind must be goods, made or addon')
        if not isinstance(e.get('unit'), str) or not e['unit'].strip():
            p.append(f'{n}: unit missing')
        for u in e.get('units') or []:
            if not (isinstance(u, list) and len(u) == 2 and isinstance(u[0], str) and isinstance(u[1], int) and 2 <= u[1] <= 1000
                    and u[0] != e.get('unit')):
                p.append(f'{n}: units must be [["pack word", integer >= 2]] different from the base unit')
        if e.get('sizes') is not None and not (isinstance(e['sizes'], list) and 2 <= len(e['sizes']) <= 6
                                              and all(isinstance(s, (str, int)) for s in e['sizes'])):
            p.append(f'{n}: sizes must be a list of 2 to 6 size letters')
    bad = [e.get('name') for e in items if concept_item(e)]
    if bad:
        p.append(f'no delivery, shipping, fee, deposit, voucher or discount items: remove {bad[:4]}')
    kinds = [e.get('kind') for e in items]
    if r['service'] and sum(str(e.get('group', '')).lower().startswith('dịch vụ') for e in items) < 4:
        p.append('at least 5 service items whose group starts with "dịch vụ"')
    if r['lots'] and kinds.count('goods') < 12:
        p.append('at least 15 goods (expiry lots)')
    if r['sizes'] and sum(bool(e.get('sizes')) for e in items) < 3:
        p.append('at least 4 items with "sizes"')
    if not r['sizes'] and any(e.get('sizes') for e in items):
        p.append('no "sizes" in this trade')
    if r['weighed'] and sum(e.get('unit') == 'kg' and e.get('kind') == 'goods' for e in items) < 4:
        p.append('at least 5 goods with unit "kg"')
    if r['addon']:
        g = d.get('addon_group')
        if not g or sum(e.get('kind') == 'addon' and e.get('group') == g for e in items) < 3:
            p.append('addon_group with at least 3 items of that group with kind "addon"')
        if r['visits'] != 'tables' and kinds.count('made') < 5:
            p.append('add-ons go with made items: at least 6 items with kind "made"')
    elif 'addon' in kinds:
        p.append('no "addon" items in this trade')
    if r['visits'] == 'tables' and kinds.count('made') < len(items) // 2:
        p.append('a table-service trade: most items are made dishes/drinks')
    if r['season']:
        s = d.get('season') or {}
        try:
            (m1, d1), (m2, d2) = s['start'], s['end']
            import datetime as dt
            a = dt.date(2025, m1, d1)
            b = dt.date(2025 if (m2, d2) >= (m1, d1) else 2026, m2, d2)
            if not 30 <= (b - a).days <= 150 or not str(s.get('label', '')).strip():
                raise ValueError
        except Exception:      # noqa: BLE001
            p.append('season must be {"label": "mùa ...", "start": [month, day], "end": [month, day]}, 40 to 120 days')
    if not (isinstance(d['unanswerable'], list) and len(d['unanswerable']) >= 2):
        p.append('unanswerable: 3 questions')
    try:
        lo, hi = d['orders']
        assert 1 <= float(lo) < float(hi) <= 400
        assert 0.1 <= float(d['tet']) <= 4 and 1.0 <= float(d['lines']) <= 6
    except Exception:          # noqa: BLE001
        p.append('orders [min, max], tet and lines out of range')
    return p


def entry(d: dict, r: dict, val: bool) -> dict:
    """The registry entry (gen.industries shape) of an accepted reply; numbers clamped to the simulator's ranges."""
    lo, hi = sorted(float(x) for x in d['orders'])
    meta = {'shop_word': d['shop_word'], 'label': d['label'].strip().lower(),
            'tet': round(min(max(float(d['tet']), 0.3), 2.5), 2),
            'orders': [round(min(max(lo, 8), 150)), round(min(max(hi, lo + 5, 15), 180))],
            'lines': round(min(max(float(d['lines']), 1.2), 4.5), 2), 'staff': int(min(max(int(d.get('staff', 3)), 2), 6))}
    if r['lots']:
        meta['lots'] = True
    if r['visits']:
        meta['visits'] = r['visits']
    if r['visits'] == 'tables':
        meta['takeaway'] = 0.12
    if r['weighed']:
        meta['decimal_units'] = ['kg']
    fmt = {'word': '{n} size {s}', 'paren': '{n} ({s})'}.get(r['sizes'] or '', None)
    items = []
    for e in d['items']:
        it = {'name': re.sub(r'\s+', ' ', str(e['name'])).strip(), 'group': str(e['group']).strip().lower(),
              'unit': str(e['unit']).strip(), 'price': int(round(float(e['price']) / 500) * 500) or 500,
              'kind': e['kind']}
        if e.get('units') and e['kind'] == 'goods':
            it['units'] = [[str(u), int(f)] for u, f in e['units']]
        if fmt and e.get('sizes'):
            it.update(sizes=[str(s).upper() for s in e['sizes']], size_fmt=fmt,
                      size_step=int(round(it['price'] * 0.12 / 1000) * 1000))
        items.append(it)
    traits = {'service': bool(r['service']), 'sizes': r['sizes'] or None,
              'addon_group': (d.get('addon_group') or '').strip().lower() or None if r['addon'] else None,
              'season': None}
    if r['season']:
        s = d['season']
        traits['season'] = {'label': str(s['label']).strip().lower(), 'start': list(s['start']), 'end': list(s['end'])}
    for it in items:
        if traits['addon_group'] and it['kind'] == 'addon':
            it['group'] = traits['addon_group']
    unans = [str(q).strip() for q in d['unanswerable'] if str(q).strip()][:3]
    return {'meta': meta, 'items': items, 'traits': traits, 'unanswerable': unans, 'val': val,
            'recipe': r, 'sector': r['sector']}


def llm_config(config, **over):
    """LLM settings of a config file, with the provider's default base URL when the env var is unset (as gen.teacher)."""
    import os
    from datamate.config import load_config, load_dotenv
    load_dotenv()
    cfg = load_config(Path(config))['llm']
    env = cfg['base_url_env']
    if not os.environ.get(env):
        url = {'DEEPSEEK': 'https://api.deepseek.com', 'OPENROUTER': 'https://openrouter.ai/api/v1'}
        os.environ[env] = next((u for k, u in url.items() if k in env.upper()), '') or os.environ.get(env, '')
    return {**cfg, 'max_comment_lines': 0, 'repetition_guard': False, **over}


def make_llm(config, **over):
    from datamate.llm import LLM
    return LLM(llm_config(config, **over))


# ---------------------------------------------------------------- run
class Pool:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = dict(industries.generated())
        self.taken = existing_labels()
        self.cost = 0.0

    def avoid(self, rng, k=400):              # every trade we have: no near copies, fewer repeated themes
        labels = sorted(self.taken.values())
        return rng.sample(labels, min(k, len(labels)))

    def add(self, key, e):
        with self.lock:
            if _fold(e['meta']['label']) in self.taken or key in self.data:
                return False
            self.data[key] = e
            self.taken[_fold(e['meta']['label'])] = e['meta']['label']
            tmp = industries.PATH.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding='utf-8')
            tmp.replace(industries.PATH)
            return True


def _cost(u):
    if not u:
        return 0.0
    hit = u.get('prompt_cache_hit_tokens', 0) or 0
    miss = u.get('prompt_cache_miss_tokens', (u.get('prompt_tokens', 0) or 0) - hit)
    return (miss * PRICES[0] + hit * PRICES[1] + (u.get('completion_tokens', 0) or 0) * PRICES[2]) / 1e6


def make_one(llm, pool: Pool, seed: int, val: bool, log):
    rng = random.Random(seed)
    r = recipe(rng)
    msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user_prompt(r, pool.avoid(rng))}]
    for attempt in range(2):
        reply = llm.chat(msgs, response_format={'type': 'json_object'}, max_tokens=6000)
        c = _cost(reply.usage)
        with pool.lock:
            pool.cost += c
        try:
            d = json.loads(reply.text)
            problems = check(d, r, pool.taken, set(pool.data))
        except Exception as exc:   # noqa: BLE001
            d, problems = None, [f'not one JSON object: {exc}'[:200]]
        log({'seed': seed, 'attempt': attempt, 'recipe': r, 'usage': reply.usage, 'cost': round(c, 6),
             'problems': problems, 'key': d.get('key') if isinstance(d, dict) else None})
        if not problems:
            e = entry(d, r, val)
            return d['key'] if pool.add(d['key'], e) else None
        msgs += [{'role': 'assistant', 'content': reply.text},
                 {'role': 'user', 'content': 'Fix these problems and send the whole JSON again:\n- ' + '\n- '.join(problems[:12])}]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=300, help='trades to try (each one call, two when the first fails a check)')
    ap.add_argument('--val-share', type=float, default=0.1, help='share marked val (held out of training)')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--config', default=str(ROOT / 'config.deepseek_direct_nothink.yaml'))
    ap.add_argument('--max-usd', type=float, default=1.0)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--yes', action='store_true', help='model calls approved by the user')
    a = ap.parse_args()
    pool = Pool()
    start = a.seed * 100_000 + len(pool.data) * 7 + 1
    seeds = [start + i for i in range(a.n)]
    if a.dry_run:
        for s in seeds:
            print(recipe(random.Random(s)))
        print('----\n' + SYSTEM + '\n----\n' + user_prompt(recipe(random.Random(seeds[0])), pool.avoid(random.Random(0), 8)))
        print(f'estimate: {a.n} calls, about ${a.n * 0.0018:.2f}')
        return
    if not a.yes:
        raise SystemExit('model calls need --yes (approved by the user)')
    llm = make_llm(a.config, temperature=0.9, max_concurrency=a.workers, timeout_seconds=180)
    lock = threading.Lock()

    def log(row):
        with lock, open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    vrng = random.Random(a.seed + 99)
    t0, made = time.time(), []

    def job(s):
        if pool.cost >= a.max_usd:
            return None
        try:
            return make_one(llm, pool, s, vrng.random() < a.val_share, log)
        except Exception as exc:   # noqa: BLE001
            log({'seed': s, 'error': f'{type(exc).__name__}: {exc}'[:300]})
            return None

    with ThreadPoolExecutor(a.workers) as ex:
        for k in ex.map(job, seeds):
            if k:
                made.append(k)
                print(f'{len(made):4d} {k:28s} {pool.data[k]["meta"]["label"]:32s} ${pool.cost:.3f}', flush=True)
    print(f'{len(made)}/{a.n} trades added ({len(pool.data)} in the pool), ${pool.cost:.3f}, {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
