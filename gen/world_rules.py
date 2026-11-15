"""One rulebook per world (docs/PLAN_UNIQUE_WORLDS.md step 5): meaning from code, wording drawn per world.

compose_world(industry, rng, bank) -> gen.rulebook_gen.Composed
  1. meaning: gen.rulebook_gen.compose (changed defaults drawn from STACKABLE, absent train sections dropped) plus the
     sections of the world's trade: hand-written trades keep their SECTIONS; a generated trade (gen.industries) gets
     rows from TEMPLATES by its traits (its own heading, size letters, add-on group, season dates), each with the Rules
     fields that give the gold of exactly that text; a few rows have alternatives (another meaning, other fields).
  2. wording: every line found in the paraphrase bank (gen/assets/rule_bank.json, made once by gen.rule_bank and
     checked line by line) is swapped for one of its checked paraphrases with probability p_reword; rows inside a
     section are shuffled (their order carries no meaning; '§N' references stay valid since sections keep their
     numbers); the layout is a table, bullets (rulebook_gen.rewrite_layout) or numbered rules; the title names the set.

lines(text) -> the rule lines a bank covers (gen.rule_bank collects them over many compositions).
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from gen import industries
from gen import rulebook_gen as RG
from gen.oracle import Rules

BANK = Path(__file__).with_name('assets') / 'rule_bank.json'

# section key -> (rows, alternatives {name: (rows, Rules overrides)}); {LABEL} {SIZES} {EX} {G} {SEASON} {FROM} {TO}
# are filled per trade. The default rows say what the train-style sections say (same oracle meaning).
TEMPLATES = {
    'expiry': (RG.SECTIONS['expiry']['rows'], {}),
    'tables': (RG.SECTIONS['tables']['rows'], {k: v for k, v in RG.SECTIONS['tables']['alts'].items()}),
    'vehicles': ([
        '| Số xe, lượt xe | **số xe** trong kỳ là số **biển số** khác nhau trên các phiếu tính doanh thu (§1); '
        'mỗi phiếu là một **lượt** |',
        '| Xe quay lại | biển số có **từ 2 phiếu trở lên** (phiếu tính doanh thu, §1) trong kỳ |'],
        {'repeat3': ([
            '| Số xe, lượt xe | **số xe** trong kỳ là số **biển số** khác nhau trên các phiếu tính doanh thu (§1); '
            'mỗi phiếu là một **lượt** |',
            '| Xe quay lại | biển số có **từ 3 phiếu trở lên** (phiếu tính doanh thu, §1) trong kỳ |'],
            dict(repeat_min=3))}),
    'service': (['| Doanh thu dịch vụ, tiền công | doanh thu (§1) của các dòng có **nhóm hàng bắt đầu bằng chữ "dịch vụ"** '
                 '({SVC}…). **Tiền bán hàng hoá, tiền phụ tùng** là doanh thu các dòng còn lại |',
                 RG.SECTIONS['service']['rows'][1]], {}),
    'size_word': (['| Size {SIZES} | mặt hàng có tên kết thúc bằng `size <cỡ>` (ví dụ `{EX}`), **không phân biệt hoa '
                   'thường**; số lượng cộng như §3 |'], {}),
    'milk_tea': (['| Size {SIZES} | món có tên kết thúc bằng {PARENS}, **không phân biệt hoa thường** |'], {}),
    'weighed': (RG.SECTIONS['weighed']['rows'], {}),
    'addon': (['| {GT} | dòng nhóm `{G}` **không phải món**: không xếp hạng, không đếm số món; vẫn tính vào doanh thu |'],
              {'item': (['| {GT} | dòng nhóm `{G}` vẫn là **món** như mọi món khác: có xếp hạng, có đếm |'],
                        dict(addon_is_item=True))}),
    'season': (['| {SEASONT} năm Y | từ **{FROM}** đến **hết {TO}** năm Y |'], {}),
}
DEFAULT_OVER = {'addon': dict(addon_is_item=False)}
# a rulebook serves a whole set of shops: its title names the set, never the shop's trade
TITLES = ['bộ dữ liệu', 'bộ {N}', 'bộ đề {N}', 'tập {N}', 'bộ dữ liệu {N}', 'dữ liệu bán hàng', 'bộ kiểm tra {N}',
          'bộ train', 'bộ dev']
STYLE = (('train', 0.75), ('heavy', 0.25))   # most worlds: train wording and tables, like a real set's rulebook
MAX_SIZES = 5                                 # more size letters: the row names the size word, not the list


def _fmt_day(m, d, prev_year=False):
    return f'{d:02d}/{m:02d}' + (' năm Y − 1' if prev_year else '')


def _season_rows(ind, rng):
    """Season row + its Rules field; an alternative shifts the window (other dates, other gold)."""
    s = industries.traits(ind)['season']
    (m1, d1), (m2, d2) = s['start'], s['end']
    alt = None
    if rng.random() < 0.3:                            # the same season, other dates (the gold follows the text)
        import datetime as dt
        k = int(rng.choice([-15, -10, 10, 15]))
        a = dt.date(2025, m1, d1) + dt.timedelta(days=k)
        b = dt.date(2025, m2, min(d2, 28)) + dt.timedelta(days=k)
        (m1, d1), (m2, d2), alt = (a.month, a.day), (b.month, b.day), f'shift{k:+d}'
    cross = (m1, d1) > (m2, d2)
    fill = {'SEASONT': s['label'][:1].upper() + s['label'][1:], 'FROM': _fmt_day(m1, d1, cross), 'TO': _fmt_day(m2, d2)}
    over = dict(seasons=((industries.season_key(ind), s['label'], (m1, d1), (m2, d2)),))
    return fill, over, alt


def _fill(row, fill):
    for k, v in fill.items():
        row = row.replace('{' + k + '}', v)
    return row


def trade_sections(ind, rng, bank=None, p_reword=0.7, skip=()):
    """§6 blocks of a generated trade: (blocks, Rules overrides, parts). skip: section keys left out (a distractor
    trade never carries a section the world's own trade has: their Rules fields would clash)."""
    meta, t = industries.meta(ind), industries.traits(ind)
    label = meta['label']
    secs = sorted(industries.sections(ind) - set(skip))
    cat = industries.catalog(ind)
    sizes = industries.sizes(ind)
    fill = {'LABEL': label, 'SIZES': ', '.join(sizes) if len(sizes) <= MAX_SIZES else 'theo tên hàng',
            'G': t.get('addon_group') or '',
            'GT': (t.get('addon_group') or '').capitalize(),
            'PARENS': ' hoặc '.join(f'`({s})`' for s in sizes) if len(sizes) <= MAX_SIZES else '`(<cỡ>)`'}
    svc = sorted({e['group'] for e in cat if e['group'].startswith('dịch vụ')})
    fill['SVC'] = ', '.join(svc[:3]) if svc else 'dịch vụ'      # the trade's own service groups as the examples
    ex = [e['name'] for e in cat if re.search(r' size \S+$', e['name'])]
    fill['EX'] = ex[int(rng.integers(len(ex)))] if ex else 'Áo thun size M'
    over, parts, rows_all = {}, {'alts': {}}, []
    for key in secs:
        rows, alts = TEMPLATES[key]
        o = dict(DEFAULT_OVER.get(key, {}))
        if key == 'season':
            f2, o2, alt = _season_rows(ind, rng)
            fill.update(f2)
            o.update(o2)
            if alt:
                parts['alts'][key] = alt
        elif alts and rng.random() < 0.4:
            name = sorted(alts)[int(rng.integers(len(alts)))]
            rows, o2 = alts[name]
            o.update(o2)
            parts['alts'][key] = name
        over.update(o)
        rows_all += [_fill(reword(r, rng, bank, p_reword), fill) for r in rows]
    # one block under the trade's own heading (a foreign rulebook names its trade, not ours)
    heading = '### ' + rng.choice([label.capitalize(), f'Ngành {label}', f'Cửa hàng {label}', f'Riêng ngành {label}'])
    block = RG._section_block(heading, rows_all) if rows_all else None
    over['sections'] = tuple(secs)
    parts['sections'] = secs
    return ([block] if block else []), over, parts


# ---------------------------------------------------------------- wording
_bank_cache = {}


def load_bank(path=BANK):
    if path not in _bank_cache:
        _bank_cache[path] = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else {}
    return _bank_cache[path]


PREFIX = re.compile(r'^(\s*(?:[-*]\s+|\d+[.)]\s+)?)')


def reword(line, rng, bank, p):
    alts = (bank or {}).get(line)
    if not alts or rng.random() >= p:
        return line
    new = alts[int(rng.integers(len(alts)))]
    lead = PREFIX.match(line).group(1)
    return lead + new[len(PREFIX.match(new).group(1)):] if lead else new     # a bullet stays a bullet


def lines(text):
    """Rule lines a paraphrase may replace: table rows (not header/rule rows) and prose lines; no headings."""
    out = []
    for ln in text.split('\n'):
        st = ln.strip()
        if not st or st.startswith('#'):
            continue
        if st.startswith('|'):
            cells = [c.strip() for c in st.strip('|').split('|')]
            if all(re.fullmatch(r':?-{3,}:?', c) for c in cells) or tuple(cells[:2]) in RG.HEADER_ROWS:
                continue
        out.append(ln)
    return out


def _shuffle_rows(text, rng, p=0.5):
    """Rows of a table keep their meaning in any order: shuffle some tables (header rows stay first)."""
    out, block = [], []

    def flush():
        if len(block) > 3 and rng.random() < p:
            head, body = block[:2], block[2:]
            order = rng.permutation(len(body)).tolist()
            block[:] = head + [body[i] for i in order]
        out.extend(block)
        block.clear()
    for ln in text.split('\n'):
        if ln.strip().startswith('|'):
            block.append(ln)
        else:
            flush()
            out.append(ln)
    flush()
    return '\n'.join(out)


def numbered_layout(text):
    """Rows become numbered rules under each section: '1.3. **X**: Y'."""
    out, sec, n = [], '0', 0
    for ln in text.split('\n'):
        m = re.match(r'^## (\d+)\.', ln)
        if m:
            sec, n = m.group(1), 0
        st = ln.strip()
        if st.startswith('|') and st.endswith('|'):
            cells = [c.strip() for c in st.strip('|').split('|')]
            if all(re.fullmatch(r':?-{3,}:?', c) for c in cells) or tuple(cells[:2]) in RG.HEADER_ROWS \
                    or cells[0] == 'type':                     # the header of the answer-format table
                continue
            n += 1
            if len(cells) == 2:
                out.append(f'{sec}.{n}. **{cells[0].replace("**", "")}**: {cells[1]}')
            else:
                out.append(f'{sec}.{n}. ' + ' — '.join(c for c in cells if c))
        else:
            out.append(ln)
    return '\n'.join(out)


def compose_world(industry, rng, bank=None, p_reword=0.7, exclude=(), distractors=None):
    """Rulebook (text + Rules + parts) of one world. bank: {line: [paraphrases]} (load_bank()).
    style 'train' (75 %): train wording, tables, few reworded lines (a real set's rulebook is the train text plus rows
    and trade sections); 'heavy' (25 %): bank paraphrases, shuffled rows, bullets or numbered rules.
    distractors: other generated trades whose sections go in §6 too (a set's rulebook covers many trades; the agent
    has to pick its shop's section); None = 2-5 drawn from the generated pool."""
    style = STYLE[0][0] if rng.random() < STYLE[0][1] else STYLE[1][0]
    profile = 'mixed' if style == 'train' else str(rng.choice(['mixed', 'reworded']))
    p = p_reword if style == 'heavy' else 0.0
    gen_trade = industries.is_generated(industry)
    comp = RG.compose([] if gen_trade else [industry], rng, profile, n_variants=int(rng.choice([0, 1, 1, 2, 2, 3])),
                      exclude=exclude)
    text, over, parts = comp.text, {}, dict(comp.parts)
    blocks, own = [], set()
    if gen_trade:
        b, o, p2 = trade_sections(industry, rng, bank, p)
        blocks += b
        over.update(o)
        own = set(p2['sections'])
        parts['alts'] = {**parts.get('alts', {}), **p2['alts']}
        parts['sections'] = p2['sections']
    if distractors is None:
        val = bool(industries.generated().get(industry, {}).get('val'))   # train worlds never show a val trade
        pool = [k for k in industries.keys(val=val) if k != industry]
        k = int(rng.integers(2, 6)) if pool else 0
        distractors = [pool[i] for i in rng.choice(len(pool), size=min(k, len(pool)), replace=False)] if k else []
    seasons = tuple(over.get('seasons', comp.rules.seasons))
    for d in distractors:
        b, o, _ = trade_sections(d, rng, bank, p, skip=own)   # only its season joins the Rules (own key)
        blocks += b
        seasons += tuple(o.get('seasons', ()))     # another trade's season: its own key, never asked here
    if blocks:
        order = rng.permutation(len(blocks)).tolist()
        text = RG._insert_sections(text, [blocks[i] for i in order])
    if seasons:
        over['seasons'] = seasons
    parts['distractors'] = list(distractors)
    n, out = 0, []
    for ln in text.split('\n'):                     # wording: paraphrases of the bank, line by line
        new = reword(ln, rng, bank, p)
        n += new != ln
        out.append(new)
    text = '\n'.join(out)
    layout = 'table'
    if style == 'heavy':
        text = _shuffle_rows(text, rng)
        layout = str(rng.choice(['table', 'bullets', 'numbered']))
    if layout == 'bullets':
        text = RG.rewrite_layout(text)
    elif layout == 'numbered':
        text = numbered_layout(text)
    title = rng.choice(TITLES).replace('{N}', str(rng.choice(['A', 'B', 'C', 'D', '1', '2', '3', 'mới', 'mở rộng'])))
    text = re.sub(r'^# DataMate — Rulebook \([^)]*\)', f'# DataMate — Rulebook ({title})', text, count=1, flags=re.M)
    parts.update(style=style, layout=layout, bank_lines=n, title=title)
    rules = replace(comp.rules, **over) if over else comp.rules
    return RG.Composed(text, rules, parts)

