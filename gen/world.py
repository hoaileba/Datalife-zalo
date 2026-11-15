"""Unique worlds (docs/PLAN_UNIQUE_WORLDS.md): every question its own shop, files, README and rulebook.

One world = one mini split, the layout gen.teacher / datamate.runner read:
  <out>/<wid>/{rulebook.md, calendar.csv, data/<wid>/{files..., README.md}, questions.jsonl (1 line), answers.jsonl,
               meta.jsonl, _world.json}
  <out>/manifest.jsonl   one row per world (hashes: no rulebook, file set or question repeats)

Per world (seeded, rebuilt the same from its seed):
  1. trade: a generated one (gen.industries; val trades only with --val) or a hand-written one (--trades);
  2. rulebook: gen.world_rules.compose_world (changed defaults, the trade's own sections, paraphrased lines, layout);
  3. data: gen.sim (spec drawn for the trade) -> gen.render (an export family the ledger allows);
  4. names: 'opaque' (t_8kq2.csv, Sheet3, tbl_a7: the files say nothing), 'semantic' (gen.reskin synonyms) or
     'mixed' (some of each); headers get synonyms; status/payment labels are left as rendered (answers stay valid);
     the copy is read back with datamate.data.load_business and compared table by table (gen.reskin.compare);
  5. README: the rendered one with the new names (gen.reskin.rewrite_readme, a detail level drawn); with opaque
     names a line per file says what it holds, except at the brief level; with --llm-readme DeepSeek rewrites it in a
     drawn voice and the rewrite is kept only if every name, the data end date and every number stay;
  6. question: gen.questions.sample (one), its gold by gen.oracle under the world's Rules, the text by gen.surface.

  PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
  $PY -m gen.world --out data_gen/uniq --n 30 --seed 0 --jobs 6 [--llm-readme --yes] [--val] [--trades cosmetics,...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import string
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

TRAIN = ROOT / 'data' / 'train'
NAMING = (('opaque', 0.1), ('semantic', 0.9))        # real sets name their files; opaque names in a few worlds
README_LEVELS = (('full', 0.6), ('partial', 0.27), ('brief', 0.13))   # ~13 % of train READMEs have no column docs
P_ROLE = 0.5                                          # an opaque file gets a 'what it holds' line half the time
CUSTOMER_ID_INTENTS = {'top_customers', 'customers_min_orders', 'customers_min_orders_share', 'customer_count',
                       'debt_customers', 'debt_top', 'debt_new_paid'}
HARD_PREFIX = ('debt', 'stock', 'purchase', 'avg_purchase', 'qty_unit', 'expiring', 'nearest_lot', 'out_of_stock',
               'gross_profit', 'net_profit', 'unsold')
P_BOOLEAN = 0.3                                       # boolean answers: right half the time by chance; ~2 % like train
P_UNANSWERABLE, P_SEEK_MOVED, QUESTION_TRIES = 0.5, 0.35, 10  # dry build 200: unanswerable 2-4 %, moved ~25 %
MOVED_ONLY = False         # --moved-only (batch B9): every world asks a question its own rulebook answers differently
OPAQUE_PREFIX = ('t_', 'tbl_', 'data_', 'file_', 'bang_', 'f_', 'sheet_', 'tab_', 'ds_', 'x')
PERIOD_RE = re.compile(r'^(.*?)([_\- ](?:\d{1,2}|20\d{2}))?$')
MONTH_SHEET = re.compile(r'(?i)^(?:T|Thang |Tháng )?\d{1,2}$')       # a month sheet of a yearly file: kept
# what a rendered file or sheet holds, by its folded name (gen.render file names): the README line of an opaque name
ROLES = {
    'banggia': 'bảng giá bán theo thời gian', 'baocaobanhang': 'báo cáo bán hàng', 'baocaotonkho': 'báo cáo tồn kho',
    'danhsachhanghoa': 'danh sách hàng hoá', 'danhmuc': 'danh mục hàng', 'danhsachchitietnhaphang': 'chi tiết từng dòng nhập hàng',
    'danhsachdonvitinh': 'đơn vị tính và hệ số quy đổi', 'danhsachhoadon': 'danh sách hoá đơn (mỗi dòng một đơn)',
    'danhsachhoadonchitiet': 'chi tiết hoá đơn (mỗi dòng một mặt hàng của đơn)',
    'danhsachhoadonchitietlo': 'lô hàng xuất theo từng dòng hoá đơn', 'danhsachkhachhang': 'danh sách khách hàng',
    'danhsachlohang': 'danh sách lô hàng và hạn dùng', 'danhsachnhaphang': 'danh sách phiếu nhập hàng',
    'danhsachquydoi': 'bảng quy đổi đơn vị', 'danhsachsanpham': 'danh sách sản phẩm', 'donhangchitiet': 'chi tiết đơn hàng',
    'dulieubanhang': 'dữ liệu bán hàng', 'dulieuxuat': 'dữ liệu xuất từ phần mềm', 'sobanhang': 'sổ bán hàng',
    'sochiphi': 'sổ chi phí', 'sonhaphang': 'sổ nhập hàng', 'soquy': 'sổ quỹ thu chi', 'sochitietbanhang': 'sổ chi tiết bán hàng',
    'tonkho': 'tồn kho', 'banhang': 'bán hàng (mỗi dòng một mặt hàng)', 'chinhanh': 'chi nhánh', 'chiphi': 'chi phí',
    'chitietdon': 'chi tiết đơn (mỗi dòng một mặt hàng)', 'chitietdonlo': 'lô xuất theo từng dòng đơn',
    'chitietnhap': 'chi tiết nhập hàng', 'donhang': 'đơn hàng (mỗi dòng một đơn)', 'donvisp': 'đơn vị và quy đổi của sản phẩm',
    'items': 'danh mục sản phẩm', 'khachhang': 'khách hàng', 'lichsugia': 'lịch sử giá bán', 'lohang': 'lô hàng',
    'luotphucvu': 'lượt phục vụ (bàn, khách)', 'nhacungcap': 'nhà cung cấp', 'nhanvien': 'nhân viên',
    'ordersexport': 'đơn hàng xuất từ Google Sheets', 'phieunhap': 'phiếu nhập', 'sanpham': 'sản phẩm',
    'thanhtoan': 'các lần thanh toán', 'thekho': 'thẻ kho (nhập xuất từng ngày)', 'trahang': 'phiếu trả hàng',
    'uom': 'đơn vị tính và quy đổi', 'tonghopngay': 'tổng hợp theo ngày', 'quydoi': 'bảng quy đổi đơn vị',
    'danhmuchang': 'danh mục hàng',
}


# ---------------------------------------------------------------- names
def opaque_stem(rng: random.Random, used: set, end=None) -> str:
    for _ in range(50):
        kind = rng.random()
        if kind < 0.7:
            body = ''.join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(rng.randint(2, 4)))
            stem = rng.choice(OPAQUE_PREFIX) + body + rng.choice(string.ascii_lowercase)
        elif kind < 0.85:
            import datetime as dt
            d = (end or dt.date(2026, 6, 30)) + dt.timedelta(days=rng.randint(0, 20))   # exported after the last record
            stem = f'export_{d:%Y%m%d}' + rng.choice('abcdefgh')
        else:
            stem = rng.choice(['Book', 'Untitled', 'Data', 'Copy of data', 'Export']) + rng.choice(string.ascii_uppercase) \
                + str(rng.randint(1, 9)) + rng.choice('abcxyz')
        if stem.lower() not in used:
            used.add(stem.lower())
            return stem
    raise RuntimeError('no opaque name left')


def opaque_sheet(rng, k, used, sql=False):
    for _ in range(50):
        name = (rng.choice(['tbl_', 't_', 'tb', 'data_']) + ''.join(rng.choice(string.ascii_lowercase + string.digits)
                                                                       for _ in range(3)) + rng.choice('abcdefgh')) if sql \
            else rng.choice([f'Sheet{k}', f'Trang{k}', f'S{k}', f'tab{k}{rng.choice("abc")}', f'Data{k}'])
        if name.lower() not in used:
            used.add(name.lower())
            return name
    return f'tbl{k}_{rng.randint(100, 999)}'


def plan_names(orig, files, rng: random.Random, mode: str, end=None):
    """A gen.reskin.Plan: header synonyms, file/sheet/table names by the naming mode, no label change."""
    from gen import reskin as R
    plan = R.plan_shop(orig, files, rng, p_label=0.0)
    if mode == 'semantic':
        return plan
    used = {Path(f).stem.lower() for f in files} | {str(n).lower() for n in plan.files.values()}
    stems = {}
    for f in sorted(files):
        if mode == 'mixed' and rng.random() < 0.5:
            continue
        p = Path(f)
        m = PERIOD_RE.match(p.stem)
        base, suffix = m.group(1), m.group(2) or ''
        if base not in stems:
            stems[base] = opaque_stem(rng, used, end)
        plan.files[f] = stems[base] + suffix + p.suffix
    k = 0
    for f, sf in files.items():
        if mode == 'mixed' and f not in plan.files and rng.random() < 0.5:
            continue
        if sf.kind == 'sqlite':          # SQLite tables keep meaningful names (their columns are meaningful too)
            continue
        for s in sf.sheets:
            if s.name is None or R.PERIOD_SHEET.match(s.name) or MONTH_SHEET.match(s.name):
                continue
            k += 1
            plan.sheets[R._sheet_key(f, s.name)] = opaque_sheet(rng, k, used, sql=sf.kind == 'sqlite')
    R._drop_ambiguous(plan, files)
    return plan


def humanize(name: str) -> str:
    """What a file or sheet holds: ROLES by its folded name, else its own words."""
    from gen import reskin as R
    from gen.industry_gen import _fold
    words = ' '.join(R.name_words(Path(name).stem)).lower()
    return ROLES.get(re.sub(r'[^a-z]', '', _fold(words)), words)


def file_lines(plan, files, level, rng, mode):
    """'## File' entries that say what an opaque file holds (real READMEs do not describe meaningful names): only in
    opaque worlds, never at the brief level, each file with probability P_ROLE; period sheets never listed."""
    from gen import reskin as R
    out = {}
    if mode != 'opaque' or level == 'brief':
        return out
    for f, sf in files.items():
        nf = plan.files.get(f, f)
        if nf == f or rng.random() >= P_ROLE:
            continue
        what = humanize(PERIOD_RE.match(Path(f).stem).group(1))
        pairs = [(plan.sheets[R._sheet_key(f, s.name)], humanize(s.name)) for s in sf.sheets
                 if s.name and R._sheet_key(f, s.name) in plan.sheets and not R.GENERIC_SHEET.match(s.name)
                 and not R.PERIOD_SHEET.match(s.name) and not MONTH_SHEET.match(s.name)]
        word = 'bảng' if sf.kind == 'sqlite' else 'sheet'
        tail = ('; ' + ', '.join(f'{word} `{a}`: {b}' for a, b in pairs)) if pairs and sf.kind != 'csv' else ''
        out[nf] = f'{what}{tail}'
    return out


def readme_with_roles(text, roles):
    """Add ' — <what it holds>' to the '- `file` (kind)' lines of '## File'."""
    def sub(m):
        name = m.group(1)
        return m.group(0) + (f' — {roles[name]}' if name in roles else '')
    return re.sub(r'^- `([^`]+)` \((?:csv|xlsx|sqlite)\)', sub, text, flags=re.M)


def write_renamed(src: Path, dst: Path, calendar: Path, plan, files, orig, tries=5):
    """gen.reskin.reskin_shop with a given plan: write, read back, compare; renames the reader sees differently go back."""
    from datamate.data import load_business
    from gen import reskin as R
    from gen.shopio import write_shop
    problems, tables = [], {}
    for _ in range(tries):
        if dst.exists():
            shutil.rmtree(dst)
        write_shop(R.apply_plan(files, plan), dst)
        new = load_business(dst, calendar, None)
        tables, problems = R.compare(orig, new, plan)
        if new.unreadable:
            problems.append(('table', '*', f'unreadable: {new.unreadable}'))
        if not problems or not R.revert(plan, problems, files):
            break
    plan.tables = tables if not problems else {}
    return problems


# ---------------------------------------------------------------- README by the model
VOICES = ['ngắn gọn, câu ngắn', 'kỹ hơn một chút, giải thích từng quy ước', 'giọng ghi chú kèm phần mềm bán hàng',
          'giọng người chủ cửa hàng ghi lại', 'giọng kế toán, đúng thuật ngữ']

README_SYSTEM = """You reword the README of a Vietnamese shop's data folder. Keep its template: the same headings in the same order (the "# Dữ liệu ..." title, "## File", "## Bảng" if present, every "## Cột trong ..." heading verbatim, "## Quy ước"), the bullet lists as lists, and the sentence "Dữ liệu có đến hết dd/mm/yyyy" word for word. Reword only the prose: the intro paragraph, the descriptions after column names, the convention sentences. No greeting, no letter style, no sign-off. Keep every qualifier word for word: "trên dòng", "của dòng", "trên đơn", "của đơn", "trước giảm", "sau giảm", "cả đơn", "từng dòng". Keep EVERY fact: every file, sheet, table and column name exactly as written inside `backticks` or **bold** (copy them character for character), every number and date, every convention (how returns, units, fees, debts, statuses are written). You may reorder, merge sentences, change headings and wording; do not invent facts, do not drop any. When a file line says what the file holds, keep that meaning in your words. Do not use the words in brackets as file names. Reply with the README text only (markdown), no code fence."""


QUALIFIERS = ('trên dòng', 'của dòng', 'trên đơn', 'của đơn', 'trước giảm', 'sau giảm', 'cả đơn', 'từng dòng')


def readme_ok(orig: str, new: str, avoid=()):
    from collections import Counter
    need = set(re.findall(r'`([^`]+)`', orig)) | set(re.findall(r'\*\*([^*]+)\*\*', orig))
    miss = [x for x in need if x not in new]
    nums = Counter(re.findall(r'\d+(?:[.,/]\d+)*', orig))
    have = Counter(re.findall(r'\d+(?:[.,/]\d+)*', new))
    lost = [n for n, c in nums.items() if have[n] < c]
    end = re.search(r'Dữ liệu có đến hết (\d{2}/\d{2}/\d{4})', orig)
    probs = []
    if miss:
        probs.append(f'names lost: {miss[:6]}')
    if lost:
        probs.append(f'numbers lost: {lost[:6]}')
    if end and end.group(0) not in new:
        probs.append('data end sentence changed')
    for q in QUALIFIERS:                                   # what a money column covers decides the computation
        if new.lower().count(q) < orig.lower().count(q):
            probs.append(f'qualifier lost: {q}')
            break
    heads = re.findall(r'^##? .*$', orig, re.M)
    if [h for h in heads if h.startswith('## ')] != [h for h in re.findall(r'^##? .*$', new, re.M) if h.startswith('## ')]:
        probs.append('headings changed')
    leak = [a for a in avoid if a and a.lower() in new.lower()]
    if leak:
        probs.append(f'old names: {leak[:4]}')
    if not 0.4 < len(new) / max(1, len(orig)) < 3:
        probs.append('length')
    return probs


def llm_readme(llm, text, rng, avoid):
    voice = rng.choice(VOICES)
    msgs = [{'role': 'system', 'content': README_SYSTEM},
            {'role': 'user', 'content': f'Voice: {voice}\n\n{text}'}]
    r = llm.chat(msgs, max_tokens=6000)
    new = re.sub(r'^```\w*\n|\n```\s*$', '', r.text.strip())
    probs = readme_ok(text, new, avoid)
    return (new if not probs else None), {'voice': voice, 'problems': probs, 'usage': r.usage}


# ---------------------------------------------------------------- one world
def pick_trade(rng, trades):
    return trades[int(rng.integers(len(trades)))]


def intent_weights(parts, boost=None):
    from gen.questions import WEIGHTS
    from gen.rulebook_gen import focus
    iw, pw = focus(parts)
    boost = boost or {}
    w = {k: (v ** 0.6) * iw.get(k, 1.0) * (2.0 if k.startswith(HARD_PREFIX) else 1.0) * boost.get(k, 1.0)
         for k, v in WEIGHTS.items()}
    return w, pw      # rare intents up (one question per world); the kinds the teacher fails and the filter drops x2


def debt_derivable(spec, L, rules):
    """A debt question's gold drops COD and marketplace orders (gen.oracle._debt_orders, _debt_flows): it is
    derivable only when the files show what that cut needs (payment method; channel when marketplace orders exist)."""
    if not str(spec.get('intent', '')).startswith('debt'):
        return True
    caps = L.shop.get('caps') or set()
    if 'payment_method' not in caps:
        return False
    o = L.orders
    if 'channel' not in caps and 'channel' in o and o.channel.fillna('').isin(rules.debt_skip_channels).any():
        return False
    return True


def world_base_rules(rules, parts, ind):
    """Rules with the train defaults and default section rows (gen.rulebook_gen.base_rules), the generated trade's
    template alternatives and shifted season put back too: an answer that differs is 'moved' by the world's text."""
    from dataclasses import replace
    from gen import industries
    from gen.rulebook_gen import SECTIONS, base_rules
    from gen.world_rules import DEFAULT_OVER, TEMPLATES
    alts = dict(parts.get('alts') or {})
    gen_alts = {k: v for k, v in alts.items() if k == 'season' or (industries.is_generated(ind) and k in TEMPLATES)}
    rest = {k: v for k, v in alts.items() if k not in gen_alts and (k == 'addon' or k in SECTIONS)}
    base = base_rules(rules, {**parts, 'alts': rest}) if parts.get('variants') or rest else rules
    fields = {}
    for k, alt in gen_alts.items():
        if k == 'season':
            s = industries.traits(ind)['season']
            fields['seasons'] = ((industries.season_key(ind), s['label'], tuple(s['start']), tuple(s['end'])),)
        else:
            from gen.oracle import Rules
            for f in TEMPLATES[k][1][alt][1]:
                fields[f] = DEFAULT_OVER.get(k, {}).get(f, getattr(Rules(), f))
    return replace(base, **fields) if fields else base


def build_world(wid: str, seed: int, out_root: Path, trades, llm_cfg=None, bank=None, boost=None):
    from datamate.data import load_business
    from gen import render as R
    from gen import surface as S
    from gen.build import TRAIN_FAMILY_WEIGHTS, _codes, _text_values, answer_alias, pick_family
    from gen.oracle import answer, undetermined
    from gen.questions import sample
    from gen.rulebook_gen import base_rules
    from gen.shopio import read_shop
    from gen.sim import make_spec, simulate
    from gen.world_rules import compose_world, load_bank

    rng = np.random.default_rng(seed)
    prng = random.Random(seed)
    ind = pick_trade(rng, trades)
    comp = compose_world(ind, rng, bank if bank is not None else load_bank())
    rules = comp.rules
    spec = make_spec(ind, rng, wid)
    L = simulate(spec, int(rng.integers(1 << 30)))
    fams = R.families_for(L)
    money = [k for k, on in (('shipping', rules.revenue_shipping), ('order_discount', rules.revenue_order_discount)) if on]
    if money:
        fams = [f for f in fams if f != 'B']
    fam = pick_family(fams, rng, TRAIN_FAMILY_WEIGHTS)
    shown = list(money)
    if fam != 'B':
        for k in ('shipping', 'order_discount'):
            if k not in shown and rng.random() < 0.35:
                shown.append(k)
    split = out_root / wid
    if split.exists():
        shutil.rmtree(split)
    raw = split / '_raw' / wid
    from gen import noise as N
    nz = N.draw_noise(rng)
    nz.verbosity = prng.choices([l for l, _ in README_LEVELS], [w for _, w in README_LEVELS])[0]   # the one README level
    rendered = R.render(L, fam, raw, rng, noise=nz, order_money=tuple(shown))
    L.shop['caps'] = set(rendered['caps'])
    shutil.copy(TRAIN / 'calendar.csv', split / 'calendar.csv')
    cal = split / 'calendar.csv'
    from gen.world_layout import relayout             # monthly files, a master workbook (README follows; read back)
    layout = relayout(raw, raw.with_name(wid + '_l'), cal, rng)
    if layout['monthly'] or layout['master']:
        shutil.rmtree(raw)
        raw.with_name(wid + '_l').rename(raw)
    # names
    files = read_shop(raw)
    orig = load_business(raw, cal, None)
    mode = prng.choices([m for m, _ in NAMING], [w for _, w in NAMING])[0]
    plan = plan_names(orig, files, prng, mode, L.shop['end'])
    plan.readme = 'full'                     # the render already chose the README level: the rename drops no more
    shop = split / 'data' / wid
    problems = write_renamed(raw, shop, cal, plan, files, orig)
    if problems:
        raise RuntimeError(f'rename check failed: {problems[:3]}')
    from gen import reskin as RS
    nm = RS.name_map(plan, orig, files)
    readme0 = (raw / 'README.md').read_text(encoding='utf-8')
    readme = RS.rewrite_readme(readme0, plan, nm, random.Random(seed + 1), RS._sales_files(orig, plan))
    readme = readme_with_roles(readme, file_lines(plan, files, nz.verbosity, prng, mode))
    readme_info = {'level': nz.verbosity, 'llm': False}
    if llm_cfg is not None and prng.random() < 0.7:
        from datamate.llm import LLM
        avoid = [s for s in (Path(f).stem for f in plan.files) if len(s) > 4 and s.lower() not in readme.lower()]
        new, info = llm_readme(LLM(llm_cfg), readme, prng, avoid)
        readme_info.update(info, llm=new is not None)
        if new is not None:
            readme = new
    (shop / 'README.md').write_text(readme, encoding='utf-8')
    shutil.rmtree(split / '_raw')
    (split / 'rulebook.md').write_text(comp.text, encoding='utf-8')
    # question
    business = load_business(shop, cal, None)
    if business.unreadable:
        raise RuntimeError(f'unreadable: {business.unreadable}')
    weights, pw = intent_weights(comp.parts, boost)
    base = world_base_rules(rules, comp.parts, ind)
    # one question: unanswerable kept with P_UNANSWERABLE (train 2.3 %); in 60 % of the worlds whose rulebook moves a
    # default, redraws look for a question the world's own rules answer differently ('moved', ~25 % of the data)
    if MOVED_ONLY and base == rules:
        raise RuntimeError('moved-only: the rulebook moves no default')
    want_moved = base != rules and (MOVED_ONLY or prng.random() < P_SEEK_MOVED)
    q, fallback = None, None
    for _ in range(QUESTION_TRIES * (4 if MOVED_ONLY else 1)):
        qs = sample(L, rng, 1, rules=rules, mix='train', weights=weights, period_boost=pw)
        qs = [x for x in qs if not undetermined(x['spec'], rules, L)]
        if not qs:
            continue
        x = qs[0]
        if x['type'] == 'unanswerable' and (want_moved or prng.random() >= P_UNANSWERABLE):
            continue
        if x['type'] == 'unanswerable' and x['spec']['intent'] in CUSTOMER_ID_INTENTS and 'customers' in L.shop['caps']:
            continue          # names but no codes: the rulebook identifies customers by name, the oracle cannot
        if x['type'] == 'boolean' and prng.random() >= P_BOOLEAN:
            continue
        if x['spec'].get('intent') == 'expiring_value':
            continue          # review B6-1: gold sums base_cost rounded in gen/sim.py, not derivable from the files
        if not debt_derivable(x['spec'], L, rules):
            continue          # review B5-0: debt gold cuts COD/marketplace orders the files would not show
        x['moved'] = base != rules and answer(L, x['spec'], x['as_of'], base) != (x['type'], x['answer'])
        fallback = fallback or x
        if not want_moved or x['moved']:
            q = x
            break
    if MOVED_ONLY and q is None:
        raise RuntimeError('moved-only: no question the rulebook answers differently')
    q = q or fallback
    if q is None:
        raise RuntimeError('no question')
    ctx = S.make_ctx(L, q['spec'], q['as_of'])
    text = S.noisify(S.realize(q['spec'], ctx, prng), prng)
    qid = f'q_{wid}'
    with open(split / 'questions.jsonl', 'w', encoding='utf-8') as f:
        f.write(json.dumps({'id': qid, 'business_id': wid, 'question': text, 'as_of_date': q['as_of'].isoformat()},
                           ensure_ascii=False) + '\n')
    alias = answer_alias(q['type'], q['answer'], _codes(L), _text_values(business), L.shop['caps'])
    with open(split / 'answers.jsonl', 'w', encoding='utf-8') as f:
        f.write(json.dumps({'id': qid, 'type': q['type'], 'answer': q['answer'], 'alias': alias}, ensure_ascii=False) + '\n')
    meta = {'id': qid, 'world': wid, 'seed': seed, 'intent': q['spec']['intent'], 'spec': q['spec'], 'family': fam,
            'industry': ind, 'naming': mode, 'file_layout': {k: bool(v) for k, v in layout.items()},
            'readme': readme_info.get('level'), 'readme_llm': readme_info['llm'],
            'rulebook': {k: v for k, v in comp.parts.items() if k != 'full_text'}, 'moved': q['moved'],
            'business_id': wid, 'as_of': q['as_of'].isoformat(), 'split': wid, 'type': q['type']}
    with open(split / 'meta.jsonl', 'w', encoding='utf-8') as f:
        f.write(json.dumps(meta, ensure_ascii=False, default=str) + '\n')
    names = sorted(p.name for p in shop.iterdir())
    side = {'family': fam, 'industry': ind, 'naming': mode, 'layout': layout, 'plan_files': plan.files, 'plan_sheets': plan.sheets,
            'caps': sorted(rendered['caps']), 'readme': readme_info, 'start': str(L.shop['start']), 'end': str(L.shop['end'])}
    (split / '_world.json').write_text(json.dumps(side, ensure_ascii=False, default=str, indent=1), encoding='utf-8')
    h = lambda s: hashlib.sha1(s.encode()).hexdigest()[:16]
    return {'world': wid, 'seed': seed, 'industry': ind, 'family': fam, 'naming': mode, 'intent': meta['intent'],
            'type': q['type'], 'moved': q['moved'], 'readme_llm': readme_info['llm'], 'layout': comp.parts.get('layout'),
            'variants': comp.parts.get('variants'), 'h_rulebook': h(comp.text), 'h_files': h('|'.join(names) + readme),
            'h_question': h(text)}


def _job(args):
    wid, seed, out, trades, llm_cfg, boost = args
    t0 = time.time()
    try:
        row = build_world(wid, seed, Path(out), trades, llm_cfg, boost=boost)
        row['sec'] = round(time.time() - t0, 1)
        return row
    except Exception as exc:       # noqa: BLE001
        return {'world': wid, 'seed': seed, 'error': f'{type(exc).__name__}: {exc}'[:400],
                'trace': traceback.format_exc()[-1500:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='data_gen/uniq')
    ap.add_argument('--n', type=int, default=30)
    ap.add_argument('--seed', type=int, default=0, help='world k gets seed seed*1_000_000 + k')
    ap.add_argument('--first', type=int, default=0, help='first world index (append more worlds later)')
    ap.add_argument('--jobs', type=int, default=6)
    ap.add_argument('--val', action='store_true', help='held-out generated trades only')
    ap.add_argument('--trades', default='', help='comma list instead of the generated pool')
    ap.add_argument('--llm-readme', action='store_true')
    ap.add_argument('--config', default=str(ROOT / 'config.deepseek_direct_nothink.yaml'))
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--intent-boost', default='', help='JSON {intent: weight factor}: a later batch fills the intents '
                                                       'earlier batches kept few of')
    ap.add_argument('--moved-only', action='store_true', help='every world asks a question its own rules answer '
                                                               'differently from the defaults (a world that has none is skipped)')
    ap.add_argument('--seen', nargs='*', default=[], help='manifest.jsonl of earlier batches: their hashes count as seen')
    a = ap.parse_args()
    boost = json.loads(Path(a.intent_boost).read_text(encoding='utf-8')) if a.intent_boost else None
    global MOVED_ONLY
    MOVED_ONLY = a.moved_only                      # forked workers inherit it
    from gen import industries
    trades = a.trades.split(',') if a.trades else industries.keys(val=a.val)
    if not trades:
        raise SystemExit('no trades: run gen.industry_gen first or pass --trades')
    llm_cfg = None
    if a.llm_readme:
        if not a.yes:
            raise SystemExit('--llm-readme calls the model: add --yes (approved by the user)')
        from gen.industry_gen import llm_config
        llm_cfg = llm_config(a.config, temperature=0.8, max_concurrency=2, timeout_seconds=180)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    man = out / 'manifest.jsonl'
    seen = {k: set() for k in ('h_rulebook', 'h_files', 'h_question')}
    for mf in [man, *map(Path, a.seen)]:
        if not mf.exists():
            continue
        for ln in mf.read_text(encoding='utf-8').splitlines():
            r = json.loads(ln)
            for k in seen:
                if k in r:
                    seen[k].add(r[k])
    # business ids like the real ones (biz_<number>); val worlds in their own number range
    jobs = [(f'biz_{(500_000 if a.val else 0) + a.seed * 10_000 + k + 1000}', a.seed * 1_000_000 + k + (7 if a.val else 0),
             str(out), trades, llm_cfg, boost) for k in range(a.first, a.first + a.n)]
    ok = bad = dup = 0
    t0 = time.time()
    with ProcessPoolExecutor(a.jobs) as ex, open(man, 'a', encoding='utf-8') as fm:
        for row in ex.map(_job, jobs):
            if 'error' in row:
                bad += 1
                print(f"{row['world']} ERROR {row['error']}", flush=True)
                shutil.rmtree(out / row['world'], ignore_errors=True)
                continue
            clash = [k for k in seen if row[k] in seen[k]]
            if clash:
                dup += 1
                print(f"{row['world']} DUPLICATE {clash}: dropped", flush=True)
                shutil.rmtree(out / row['world'], ignore_errors=True)
                continue
            for k in seen:
                seen[k].add(row[k])
            fm.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
            fm.flush()
            ok += 1
            print(f"{row['world']} {row['industry'][:22]:22s} {row['family']} {row['naming']:8s} {row['intent'][:22]:22s} "
                  f"{row['layout']:8s} readme_llm={row['readme_llm']} {row['sec']}s", flush=True)
    print(f'{ok} worlds, {bad} errors, {dup} duplicates, {time.time() - t0:.0f} s -> {out}')


if __name__ == '__main__':
    main()
