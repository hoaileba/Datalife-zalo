"""Split rulebooks for synthetic splits (Direction 3): the train rulebook plus sections for the split's new business
types, changed defaults, dropped sections of absent train business types and reworded lines, with the oracle Rules
that give the gold of exactly that text.

A split's rulebook is shared by every shop of the split (docs/zac/data.md), so one composition = one split:

  compose(industries, rng, profile) -> Composed(text, rules, parts)
    profile 'train'    : train rulebook + sections of the new business types (default definitions)
    profile 'mixed'    : + 1-3 changed defaults (gen.variants and EXTRA below) + alternative section definitions
                         + reworded lines (same meaning) + absent train sections dropped
    profile 'reworded' : like 'train' but many lines reworded (no meaning change) and absent sections dropped
    profile 'rewrite'  : 'reworded' + every rule line retyped as a bullet with other words (datamate.rules aligns the
                         retyped rules by name: only changed meanings are listed), meaning unchanged; changed defaults only when forced

Every changed meaning is a Rules field (gen.oracle), so the gold follows the text; a reworded line keeps its meaning
(the agent sees it in rulebook_changes and loses its cookbook recipe, as with a real foreign rulebook). Section
definitions are made up from general knowledge of the trades, never from another split's rulebook.

python -m gen.rulebook_gen --industries hotpot,fashion --profile mixed --seed 3   # prints the text and the changes
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from gen import variants  # noqa: E402
from gen.oracle import Rules  # noqa: E402

TRAIN_RULEBOOK = ROOT / 'data' / 'train' / 'rulebook.md'
HEAD = '| Luật | Mặc định |\n|---|---|'

# ---------------------------------------------------------------- industry sections
# key -> {'industries', 'heading', 'rows': [(row text, Rules overrides)], 'alts': {name: ([rows], overrides)}}
# Rows are markdown table rows; alternatives replace the default rows of the same section.
SECTIONS = {
    'tables': {
        'industries': ('restaurant', 'hotpot'),
        'heading': '### Nhà hàng, quán ăn (bàn và khách)',
        'rows': [
            '| Số khách | cộng **số khách** ghi trên các đơn tính doanh thu (§1) trong kỳ. Đơn không ghi số khách '
            '(đơn mang về) **không** tính khách |',
            '| Doanh thu bình quân một khách | doanh thu (§1) chia cho số khách cùng kỳ, làm tròn về đồng |',
            '| Doanh thu theo khu vực, theo bàn | theo khu vực, bàn ghi trên đơn; đơn mang về không thuộc bàn nào. '
            '**Bàn doanh thu cao nhất** xếp theo doanh thu (§1), bằng nhau thì theo mã bàn |',
        ],
        'over': {},
        'alts': {
            'guests_one': ([
                '| Số khách | cộng **số khách** ghi trên các đơn tính doanh thu (§1) trong kỳ. Đơn không ghi số khách '
                '(đơn mang về) tính là **1 khách** |',
                '| Doanh thu bình quân một khách | doanh thu (§1) chia cho số khách cùng kỳ, làm tròn về đồng |',
                '| Doanh thu theo khu vực, theo bàn | theo khu vực, bàn ghi trên đơn; đơn mang về không thuộc bàn nào. '
                '**Bàn doanh thu cao nhất** xếp theo doanh thu (§1), bằng nhau thì theo mã bàn |',
            ], dict(guests_missing_as_one=True)),
            'per_guest_thousand': ([
                '| Số khách | cộng **số khách** ghi trên các đơn tính doanh thu (§1) trong kỳ. Đơn không ghi số khách '
                '(đơn mang về) **không** tính khách |',
                '| Doanh thu bình quân một khách | doanh thu (§1) chia cho số khách cùng kỳ, làm tròn đến **nghìn '
                'đồng** (nửa nghìn làm tròn lên) |',
                '| Doanh thu theo khu vực, theo bàn | theo khu vực, bàn ghi trên đơn; đơn mang về không thuộc bàn nào. '
                '**Bàn doanh thu cao nhất** xếp theo doanh thu (§1), bằng nhau thì theo mã bàn |',
            ], dict(per_guest_round=-3)),
        },
    },
    'service': {
        'industries': ('motorbike_repair', 'spa_salon', 'pet_shop', 'phone_shop'),
        'heading': '### Cửa hàng có dịch vụ (sửa xe, salon, spa, thú cưng, sửa điện thoại)',
        'rows': [
            '| Doanh thu dịch vụ, tiền công | doanh thu (§1) của các dòng có **nhóm hàng bắt đầu bằng chữ "dịch vụ"** '
            '(dịch vụ, dịch vụ tóc, dịch vụ da…). **Tiền bán hàng hoá, tiền phụ tùng** là doanh thu các dòng còn lại |',
            '| Tỉ trọng dịch vụ | doanh thu dịch vụ chia cho doanh thu **cả shop** cùng kỳ (§1), làm tròn như mọi '
            'phần trăm (§9) |',
        ],
        'over': {},
        'alts': {},
    },
    'vehicles': {
        'industries': ('motorbike_repair',),
        'heading': '### Sửa xe máy',
        'rows': [
            '| Số xe, lượt xe | **số xe** trong kỳ là số **biển số** khác nhau trên các phiếu tính doanh thu (§1); '
            'mỗi phiếu là một **lượt** |',
            '| Xe quay lại | biển số có **từ 2 phiếu trở lên** (phiếu tính doanh thu, §1) trong kỳ |',
        ],
        'over': {},
        'alts': {
            'repeat3': ([
                '| Số xe, lượt xe | **số xe** trong kỳ là số **biển số** khác nhau trên các phiếu tính doanh thu (§1); '
                'mỗi phiếu là một **lượt** |',
                '| Xe quay lại | biển số có **từ 3 phiếu trở lên** (phiếu tính doanh thu, §1) trong kỳ |',
            ], dict(repeat_min=3)),
        },
    },
    'size_word': {
        'industries': ('fashion',),
        'heading': '### Thời trang',
        'rows': ['| Size S, M, L, XL | mặt hàng có tên kết thúc bằng `size <cỡ>` (ví dụ `Áo thun size M`), **không '
                 'phân biệt hoa thường**; số lượng cộng như §3 |'],
        'over': {}, 'alts': {},
    },
    'milk_tea': {
        'industries': ('milk_tea',),
        'heading': '### Trà sữa',
        'rows': ['| Size M, size L | món có tên kết thúc bằng `(M)` hoặc `(L)`, **không phân biệt hoa thường** |'],
        'over': {}, 'alts': {},
    },
    'weighed': {
        'industries': ('fruit_shop',),
        'heading': '### Trái cây, hàng cân ký',
        'rows': ['| Hàng bán theo ký | số lượng là số **kg** cân thực tế, có phần lẻ. Tổng số kg làm tròn **2 chữ số '
                 'thập phân** |'],
        'over': {}, 'alts': {},
    },
    'agri': {
        'industries': ('agri_supply',),
        'heading': '### Vật tư nông nghiệp',
        'rows': ['| Vụ Đông Xuân năm Y | từ **01/11 năm Y − 1** đến **hết 31/03 năm Y** |',
                 '| Vụ Hè Thu năm Y | từ **01/04** đến **hết 31/08** năm Y |'],
        'over': dict(seasons=(('dong_xuan', 'vụ Đông Xuân', (11, 1), (3, 31)), ('he_thu', 'vụ Hè Thu', (4, 1), (8, 31)))),
        'alts': {
            'late': (['| Vụ Đông Xuân năm Y | từ **15/11 năm Y − 1** đến **hết 15/04 năm Y** |',
                      '| Vụ Hè Thu năm Y | từ **16/04** đến **hết 15/08** năm Y |'],
                     dict(seasons=(('dong_xuan', 'vụ Đông Xuân', (11, 15), (4, 15)),
                                   ('he_thu', 'vụ Hè Thu', (4, 16), (8, 15))))),
        },
    },
    'school': {
        'industries': ('stationery',),
        'heading': '### Văn phòng phẩm',
        'rows': ['| Mùa tựu trường năm Y | từ **01/08** đến **hết 15/09** năm Y |'],
        'over': dict(seasons=(('tuu_truong', 'mùa tựu trường', (8, 1), (9, 15)),)),
        'alts': {
            'july': (['| Mùa tựu trường năm Y | từ **15/07** đến **hết 10/09** năm Y |'],
                     dict(seasons=(('tuu_truong', 'mùa tựu trường', (7, 15), (9, 10)),))),
        },
    },
    'expiry': {
        'industries': ('cosmetics', 'mother_baby', 'agri_supply'),
        'heading': '### Hàng có hạn dùng (mẹ và bé, mỹ phẩm, vật tư nông nghiệp)',
        'rows': [
            '| Hàng hết hạn trong N ngày tới | tính tại hôm nay D: lô còn tồn có hạn dùng từ D đến hết ngày D + N. '
            '**Tiền vốn** là giá trị phần **còn tồn** của lô, theo giá nhập của chính lô đó quy về đơn vị cơ bản |',
            '| Lô gần hết hạn nhất của một mặt hàng | trong các lô còn tồn chưa quá hạn tại hôm nay, lô có hạn sớm nhất |',
        ],
        'over': {}, 'alts': {},
    },
}
# toppings (trà sữa) and khăn lạnh (quán lẩu): one rule for every add-on line of the split
ADDON = {
    'not_item': ('| Topping, khăn lạnh | dòng **topping** (nhóm `topping`) và dòng **khăn lạnh** **không phải món**: '
                 'không xếp hạng, không đếm số món; vẫn tính vào doanh thu |', dict(addon_is_item=False)),
    'item': ('| Topping, khăn lạnh | dòng **topping** (nhóm `topping`) và dòng **khăn lạnh** vẫn là **món** như mọi '
             'món khác: có xếp hạng, có đếm |', dict(addon_is_item=True)),
}
ADDON_INDUSTRIES = ('milk_tea', 'hotpot')
ADDON_HEADING = '### Món kèm'

# Train business types whose §6 section a split without them may drop (as a foreign rulebook would).
TRAIN_SECTIONS = {'cafe': '### Cà phê', 'pharmacy': '### Nhà thuốc', 'building': '### Vật liệu xây dựng'}

# ---------------------------------------------------------------- changed defaults beyond gen.variants
EXTRA = {
    'bestseller_revenue': (dict(bestseller_by='revenue'), [(
        '| Bán chạy | theo **số lượng quy về đơn vị cơ bản**, không theo số dòng hay số tiền;',
        '| Bán chạy | theo **doanh thu** (§1) của mặt hàng, không theo số lượng hay số dòng;'),
        (' Mặt hàng khác đơn vị cơ bản vẫn xếp chung theo số đó.', '')]),
    'last_n_before_today': (dict(last_n_include_today=False), [(
        '| N ngày gần nhất | N ngày liền nhau **kể cả hôm nay**, ngày cuối là hôm nay |',
        '| N ngày gần nhất | N ngày liền nhau **trước hôm nay**, **không** tính hôm nay; ngày cuối là hôm qua |')]),
    'tet_from_25': (dict(tet_start=(12, 25)), [(
        'từ ngày dương của **23 tháng Chạp** (năm âm Y − 1)', 'từ ngày dương của **25 tháng Chạp** (năm âm Y − 1)'),
        ('cùng số ngày ngay trước 23 tháng Chạp', 'cùng số ngày ngay trước 25 tháng Chạp')]),
}
# variants of gen.variants that edit the same line cannot be stacked
CLASH = [{'returns_count', 'delivering_out'}, {'tet_short', 'tet_from_25'}, {'cancel_rate_no_returns', 'pct_one_decimal'}]
# variants whose effect the synthetic shops can show
STACKABLE = ['week_sunday', 'returns_count', 'delivering_out', 'revenue_shipping', 'revenue_voucher',
             'cancel_rate_no_returns', 'this_month_full_prev', 'tet_short', 'shifts_split', 'avg_purchase_simple',
             'pct_one_decimal', *EXTRA]

# Same meaning, other words (on top of gen.variants.REWORDINGS).
REWORDINGS = [
    ('Câu hỏi nói khác thì làm theo câu hỏi; không nói thì áp luật mặc định ở đây.',
     'Khi câu hỏi nói rõ cách tính thì theo câu hỏi; câu hỏi không nói thì dùng luật mặc định dưới đây.'),
    ('| Đơn thuộc kỳ nào | theo **ngày đặt**, không theo ngày giao hay ngày thu tiền |',
     '| Đơn thuộc kỳ nào | xét **ngày đặt đơn**, không xét ngày giao hàng hay ngày thu tiền |'),
    ('| Nhân viên bán giỏi nhất | theo **doanh thu** (§1) của nhân viên trong kỳ, không theo số đơn |',
     '| Nhân viên bán giỏi nhất | xếp theo **doanh thu** (§1) nhân viên đó bán được trong kỳ, không xếp theo số đơn |'),
    ('| Giá trị trung bình một đơn | làm tròn về đồng, nửa đồng làm tròn lên |',
     '| Giá trị trung bình một đơn | làm tròn tới đơn vị đồng; từ nửa đồng trở lên thì làm tròn lên |'),
    ('| Từ đầu năm, từ đầu năm tới nay | từ 01/01 của năm nay đến **hết hôm nay** |',
     '| Từ đầu năm, từ đầu năm tới nay | tính từ ngày 01/01 năm nay cho đến **hết ngày hôm nay** |'),
    ('| Nhóm hàng | theo cột nhóm hàng, đúng tên nhóm câu hỏi nêu; không gộp nhóm khác tên dù tên gần nhau |',
     '| Nhóm hàng | lấy theo cột nhóm hàng, khớp đúng tên nhóm trong câu hỏi; nhóm khác tên thì không gộp dù tên na ná |'),
]
TITLE = '# DataMate — Rulebook (bộ train)'


@dataclass
class Composed:
    text: str
    rules: Rules
    parts: dict = field(default_factory=dict)       # what was composed (for meta.jsonl / analysis)


def _apply(text, pairs, what):
    for old, new in pairs:
        if old not in text:
            raise ValueError(f'{what}: line not found: {old[:70]}')
        text = text.replace(old, new)
    return text


def _section_block(heading, rows):
    return f'{heading}\n{HEAD}\n' + '\n'.join(rows) + '\n'


def _drop_section(text, heading):
    """Remove a '### X' block of §6 (heading to the next heading)."""
    pat = re.compile(rf'^{re.escape(heading)}\n.*?(?=^#{{2,3}} )', re.S | re.M)
    out, n = pat.subn('', text)
    if n != 1:
        raise ValueError(f'section {heading} not found')
    return out


def _insert_sections(text, blocks):
    """New §6 sub-sections go right before '## 7.'."""
    i = text.index('## 7.')
    return text[:i] + ''.join(b + '\n' for b in blocks) + text[i:]


def sections_for(industries):
    return [k for k, sec in SECTIONS.items() if set(sec['industries']) & set(industries)]


# Questions a changed default moves (sampled more in its split, so the change shows in the gold): intents, period kinds
FOCUS = {
    'week_sunday': ((), ('this_week', 'last_week')),
    'delivering_out': ((), ('today', 'yesterday', 'this_week', 'last_week', 'last_n_days')),
    'cancel_rate_no_returns': (('cancel_rate',), ()),
    'this_month_full_prev': (('revenue_change_pct', 'revenue_diff'), ('this_month',)),
    'tet_short': ((), ('tet',)), 'tet_from_25': ((), ('tet',)),
    'shifts_split': (('shift_revenue', 'shift_orders', 'shift_change_pct'), ()),
    'avg_purchase_simple': (('avg_purchase_price',), ()),
    'bestseller_revenue': (('top_items',), ()),
    'last_n_before_today': ((), ('last_n_days',)),
}
# rows of the §9 format table that the 1-decimal variant of gen.variants leaves saying "2 chữ số"
PCT_ONE_EXTRA = [('Tiền đúng từng đồng, số đếm đúng từng đơn vị, phần trăm đúng 2 chữ số thập phân.',
                  'Tiền đúng từng đồng, số đếm đúng từng đơn vị, phần trăm đúng 1 chữ số thập phân.')]
HEADER_ROWS = {('Luật', 'Mặc định'), ('Cách nói', 'Nghĩa'), ('Từ', 'Nghĩa'), ('Cách ghi', 'Hiểu là')}


def rewrite_layout(text):
    """Same rules, another layout and wording on every rule line (a split writer who retyped the whole book):
    table rows become '- **X** — mặc định: Y' bullets, header rows and table rules go. Every rule line gets new words,
    datamate.rules.compare aligns them by rule name; no meaning changes."""
    out = []
    for line in text.split('\n'):
        st = line.strip()
        if st.startswith('|') and st.endswith('|'):
            cells = [c.strip() for c in st.strip('|').split('|')]
            if all(re.fullmatch(r':?-{3,}:?', c) for c in cells) or tuple(cells[:2]) in HEADER_ROWS:
                continue
            if cells[0] == 'type' or cells[:1] == ['type']:
                continue
            if len(cells) == 2:
                out.append(f'- **{cells[0].replace("**", "")}** — mặc định: {cells[1]}')
            elif len(cells) == 4:
                ex = ''.join(f'; ví dụ {w} {c}' for w, c in (('đúng', cells[2]), ('sai', cells[3])) if c)
                out.append(f'- `{cells[0]}`: định dạng {cells[1]}{ex}')
            else:
                out.append('- ' + '; '.join(c for c in cells if c))
        else:
            out.append(line)
    return '\n'.join(out)


def compose(industries, rng, profile='train', n_variants=None, title=None, force=None, exclude=(), alts=None,
            alts_exclude=()) -> Composed:
    """One split rulebook for shops of `industries` (rng: numpy Generator).
    profile: 'train' | 'mixed' | 'reworded' | 'rewrite' (see the module doc; 'rewrite' = 'reworded' + rewrite_layout).
    force: changed defaults to apply (names of gen.variants.VARIANTS / EXTRA) instead of a random draw ('mixed' draws
    1-3 when not forced); exclude: defaults never drawn (held out for val); alts: {section: alternative} forced;
    alts_exclude: alternatives never drawn."""
    text = TRAIN_RULEBOOK.read_text(encoding='utf-8')
    over, parts = {}, {'profile': profile, 'variants': [], 'alts': {}, 'dropped': [], 'reworded': 0, 'sections': []}
    if profile == 'mixed' or force:
        k = int(rng.choice([1, 1, 2, 2, 3])) if n_variants is None else n_variants
        pool = [v for v in STACKABLE if v not in exclude]
        chosen = []
        for name in (list(force) if force is not None else rng.permutation(pool).tolist()):
            if force is None and len(chosen) >= k:
                break
            if any(name in c and set(chosen) & c for c in CLASH):
                if force is not None:
                    raise ValueError(f'{name} clashes with {chosen}')
                continue
            chosen.append(name)
        for name in chosen:
            try:
                if name in EXTRA:
                    o, pairs = EXTRA[name]
                    text = _apply(text, pairs, name)
                else:
                    text = variants.rulebook_text(name, text)
                    o = variants.VARIANTS[name][0]
                if name == 'pct_one_decimal':
                    text = _apply(text, PCT_ONE_EXTRA, name)
            except ValueError:
                if force is not None:
                    raise
                continue                  # an earlier change rewrote the line this one edits
            over.update(o)
            parts['variants'].append(name)
    # industry sections
    keys = sections_for(industries)
    blocks = []
    alts = alts or {}
    for key in keys:
        sec = SECTIONS[key]
        rows, o = sec['rows'], dict(sec['over'])
        choices = sorted(a for a in sec['alts'] if a not in alts_exclude)
        alt = alts.get(key)
        if alt is None and profile == 'mixed' and choices and rng.random() < 0.5:
            alt = choices[int(rng.integers(len(choices)))]
        if alt:
            rows, o2 = sec['alts'][alt]
            o.update(o2)
            parts['alts'][key] = alt
        if 'seasons' in o:
            o['seasons'] = tuple(over.get('seasons', ())) + tuple(o['seasons'])
        over.update(o)
        blocks.append(_section_block(sec['heading'], rows))
    if set(ADDON_INDUSTRIES) & set(industries):
        mode = alts.get('addon') or ('not_item' if profile != 'mixed' or rng.random() < 0.6 else 'item')
        row, o = ADDON[mode]
        over.update(o)
        blocks.append(_section_block(ADDON_HEADING, [row]))
        parts['alts']['addon'] = mode
        keys = keys + ['addon']
    parts['sections'] = keys
    over['sections'] = tuple(keys)
    if blocks:
        text = _insert_sections(text, blocks)
    if profile in ('mixed', 'reworded', 'rewrite'):
        for ind, heading in TRAIN_SECTIONS.items():
            if ind not in industries and rng.random() < 0.8:
                text = _drop_section(text, heading)
                parts['dropped'].append(ind)
        pool = list(variants.REWORDINGS) + REWORDINGS
        k = len(pool) if profile in ('reworded', 'rewrite') else int(rng.integers(0, 4))
        n = 0
        for i in rng.permutation(len(pool))[:k].tolist():
            old, new = pool[i]
            if old in text:
                text = text.replace(old, new)
                n += 1
        parts['reworded'] = n
    if profile == 'rewrite':
        text = rewrite_layout(text)
    if title or profile != 'train':
        text = text.replace(TITLE, f'# DataMate — Rulebook ({title or "bộ dữ liệu"})')
    rules = replace(Rules(), **over)
    return Composed(text, rules, parts)


def base_rules(rules, parts):
    """The Rules of the same split with the train defaults and the default section definitions: an answer that
    differs under them is 'moved' by the split's own text."""
    fields = {}
    for nm in parts.get('variants', []):
        fields.update({f: getattr(Rules(), f) for f in (EXTRA[nm][0] if nm in EXTRA else variants.VARIANTS[nm][0])})
    for key, alt in parts.get('alts', {}).items():
        if key == 'addon':
            if alt == 'item':
                fields['addon_is_item'] = False
            continue
        sec = SECTIONS[key]
        for f in sec['alts'][alt][1]:
            fields[f] = sec['over'].get(f, getattr(Rules(), f))
    if 'seasons' in fields:                   # seasons of all sections: the default ones of each
        fields['seasons'] = tuple(x for k in parts.get('sections', []) if k in SECTIONS
                                  for x in SECTIONS[k]['over'].get('seasons', ()))
    return replace(rules, **fields)


def focus(parts):
    """(intent weight multipliers, period-kind multipliers) that make a split's changed defaults show in its gold."""
    iw, pw = {}, {}
    for name in parts.get('variants', []):
        ints, pers = FOCUS.get(name, ((), ()))
        iw.update({i: 2.0 for i in ints})
        pw.update({p: 3.0 for p in pers})
    return iw, pw


def changes_of(text):
    """What the agent will see: datamate.rules.compare against the standard (train) lines."""
    from datamate.rules import compare, load_train_units
    return compare(text, load_train_units())


def main():
    import numpy as np
    ap = argparse.ArgumentParser()
    ap.add_argument('--industries', default='hotpot,fashion,milk_tea,motorbike_repair,agri_supply')
    ap.add_argument('--profile', default='mixed')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    c = compose(a.industries.split(','), np.random.default_rng(a.seed), a.profile)
    print(c.text)
    print('----', c.parts)
    print('----', {k: v for k, v in vars(c.rules).items() if v != getattr(Rules(), k)})
    print('----', changes_of(c.text))


if __name__ == '__main__':
    main()
