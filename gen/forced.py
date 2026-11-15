"""Forced first turns for the skills the teacher rarely shows on its own (user request 2026-11-15).

A forced turn is a wrong first reply written by code from a question the teacher already answered correctly; the
host runs it as usual and the teacher writes the turns after it (gen.teacher --prefill). Only those later turns can
become samples (gen.sft.teacher_turns keeps the final turn; the forced turn is history), and only when the final
answer matches gold. Kinds:
  label         a status label of a label list replaced by a habitual one -> the label-coverage assert fails
  column        a kit.name(...) label replaced by a name the shop does not use -> KeyError listing the closest
                columns -> the teacher fixes it (CAUSE: BIND ...)
  wrong_table / syntax / precedence / item_name   the old student's most common run errors (by category only):
                a column read on another table, an unterminated string, `a == x & b == y` without parentheses,
                an item name typed from memory
  unanswerable  "unanswerable" claimed for an answerable question -> the host's check with the tables' evidence ->
                the teacher computes the answer
  percent_type  a percent answer sent as type "number" -> the host's issue -> the teacher fixes the type

  python -m gen.forced --runs 'outputs/teacher/final/p1_B[5-8]_*' ... --n column=10,unanswerable=6,percent_type=4 \
      --out data_gen/forced/pilot
writes <out>/<split-name>.prefill.jsonl and <split-name>.ids.txt per source split (gen.teacher runs one split each).
No model calls.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import random
import re
from pathlib import Path

from gen import sft

KIT_NAME = re.compile(r"""kit\.name\((\w+),\s*(['"])(.+?)\2\)""")
ROLE_NAMES = [            # constant name part -> a column name a model would assume
    (('DATE', 'NGAY', 'TIME'), ['Ngày bán', 'Ngày tạo đơn', 'order_date']),
    (('STATUS', 'TRANG'), ['Trạng thái', 'Tình trạng', 'status']),
    (('QTY', 'QUANTITY', 'SL'), ['Số lượng', 'SL bán', 'quantity']),
    (('AMOUNT', 'MONEY', 'TOTAL', 'PRICE', 'REVENUE'), ['Thành tiền', 'Doanh thu', 'amount']),
    (('ITEM', 'NAME', 'PRODUCT'), ['Tên hàng', 'Tên sản phẩm', 'product_name']),
    (('UNIT',), ['Đơn vị', 'ĐVT', 'unit']),
    (('CUSTOMER', 'KHACH'), ['Khách hàng', 'Tên khách', 'customer']),
    (('ORDER', 'INVOICE', 'BILL'), ['Mã đơn', 'Số hoá đơn', 'order_id']),
]
CLAIMS = [
    'no table records what is asked for this period',
    'the asked period is not covered by the shop data',
    'the shop data has no column for this measure',
]


def norm(s):
    from datamate.helpers import norm as n
    return n(s)


def final_reply(rec):
    """The kept single-turn final reply of a correct record, or None."""
    turns = sft.teacher_turns(rec)
    if len(turns) != 1 or not turns[0]['keep'] or not turns[0]['final']:
        return None
    ev = next(e for e in rec['trace'] if e.get('event') == 'model' and e.get('turn') == 0)
    return ev['output']


def code_of(reply):
    m = re.search(r'```python\n(.*?)```', reply, re.S)
    return m.group(1) if m else ''


def force_column(reply, rng):
    hits = [m for m in KIT_NAME.finditer(code_of(reply))]
    rng.shuffle(hits)
    for m in hits:
        line = code_of(reply)[:m.start()].rsplit('\n', 1)[-1]           # `ORDER_DATE = ` before the call
        const = line.split('=')[0].strip().upper()
        for parts, names in ROLE_NAMES:
            if any(p in const for p in parts):
                wrong = rng.choice([x for x in names if norm(x) != norm(m.group(3))] or [None])
                if wrong:
                    return reply.replace(m.group(0), f"kit.name({m.group(1)}, {m.group(2)}{wrong}{m.group(2)})", 1)
    return None


LABEL_LIST = re.compile(r"""(?m)^([A-Z_]*(?:LABELS?|STATUS(?:ES)?|KEPT|CANCEL\w*|RETURN\w*|DONE\w*))\s*=\s*\[([^\]\n]+)\]""")
GUESSED = ['completed', 'cancelled', 'returned', 'Hoàn thành', 'Đã hủy', 'Đã giao']


def force_label(reply, rng):
    """A status label list typed from habit (English or another shop's words) instead of this shop's labels: the
    teacher's label-coverage assert fails (a CHECK error)."""
    code = code_of(reply)
    if 'assert' not in code:
        return None
    hits = list(LABEL_LIST.finditer(code))
    rng.shuffle(hits)
    for m in hits:
        lits = re.findall(r"""(['"])(.+?)\1""", m.group(2))
        if not lits:
            continue
        q, old = rng.choice(lits)
        new = rng.choice([g for g in GUESSED if norm(g) != norm(old)])
        line = m.group(0).replace(f'{q}{old}{q}', f'{q}{new}{q}', 1)
        return reply.replace(m.group(0), line, 1)
    return None


def force_unanswerable(reply, rng):
    asked = re.search(r'(?m)^ASKED:\s*(.+)$', reply)
    if not asked:
        return None
    claim = rng.choice(CLAIMS)
    return (f"REASON:\nThe question asks {asked.group(1).strip()} Looking at the shop block, {claim}, so the data "
            f"cannot answer it.\nASKED: {asked.group(1).strip()}\nRULES: none\nPLAN:\nBIND: the tables listed in the "
            f"shop block.\nCOMPUTE: nothing to compute.\nCHECK: none.\n```python\n# 1. BIND: nothing holds the asked "
            f"measure\nresult = {{\"type\": \"unanswerable\", \"reason\": \"{claim}\"}}\n```")


def force_percent_type(reply, rng):
    new = re.sub(r"""(['"]type['"]\s*:\s*['"])percent(['"])""", r'\1number\2', reply, count=1)
    return new if new != reply else None


TABLE_BIND = re.compile(r"""(?m)^([A-Z_]+)\s*=\s*tables\[""")
AND_MASK = re.compile(r"""\(([^()\n]*?(?:==|!=|>=|<=|>|<)[^()\n]*?)\)\s*&\s*\(([^()\n]*?(?:==|!=|>=|<=|>|<)[^()\n]*?)\)""")
NAME_LOOKUP = re.compile(r"""kit\.norm\((['"])([^'"\n]{4,})\1\)""")


def force_wrong_table(reply, rng):
    """A column read on the wrong table (the old student's most common KeyError): kit.name(OTHER, 'col')."""
    code = code_of(reply)
    tables = TABLE_BIND.findall(code)
    hits = list(KIT_NAME.finditer(code))
    rng.shuffle(hits)
    for m in hits:
        others = [t for t in tables if t != m.group(1)]
        if others:
            return reply.replace(m.group(0), f"kit.name({rng.choice(others)}, {m.group(2)}{m.group(3)}{m.group(2)})", 1)
    return None


def force_syntax(reply, rng):
    """An unterminated string literal (the old student's most common SyntaxError)."""
    code = code_of(reply)
    lines = [l for l in code.split('\n') if re.search(r"""=\s*(['"])[^'"\n]+\1\s*$""", l) and not l.strip().startswith('#')]
    if not lines:
        return None
    line = rng.choice(lines)
    return reply.replace(line, line.rstrip()[:-1], 1)


def force_precedence(reply, rng):
    """Two comparisons joined by & without their parentheses (TypeError / ValueError at run time)."""
    hits = list(AND_MASK.finditer(code_of(reply)))
    if not hits:
        return None
    m = rng.choice(hits)
    return reply.replace(m.group(0), f'{m.group(1).strip()} & {m.group(2).strip()}', 1)


def force_item_name(reply, rng):
    """An item or group name typed from memory (a word dropped or swapped): the lookup finds nothing and the
    teacher's 'found' assert or an .iloc[0] fails."""
    hits = [m for m in NAME_LOOKUP.finditer(code_of(reply)) if len(m.group(2).split()) >= 2]
    if not hits:
        return None
    m = rng.choice(hits)
    words = m.group(2).split()
    new = ' '.join(words[:-1]) if rng.random() < 0.5 else ' '.join(words[1:] + words[:1])
    return reply.replace(m.group(0), f'kit.norm({m.group(1)}{new}{m.group(1)})', 1)


FORCE = {'column': force_column, 'label': force_label, 'wrong_table': force_wrong_table, 'syntax': force_syntax,
         'precedence': force_precedence, 'item_name': force_item_name, 'unanswerable': force_unanswerable, 'percent_type': force_percent_type}


def eligible(kind, rec):
    gold = (rec.get('gold') or {}).get('type')
    if gold == 'unanswerable':
        return False
    if kind == 'percent_type':
        return gold == 'percent'
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', nargs='+', required=True, help='teacher run folders (globs) of answered questions')
    ap.add_argument('--n', required=True, help='kind=count,... (column, unanswerable, percent_type)')
    ap.add_argument('--exclude', nargs='*', default=[], help='prefill files of earlier batches: their ids are not reused')
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    want = {k: int(v) for k, v in (x.split('=') for x in a.n.split(','))}
    used = set()
    for f in a.exclude:
        for line in open(f, encoding='utf-8'):
            used.add(json.loads(line)['id'])
    drop = set((Path(__file__).with_name('assets') / 'final_drop_ids.txt').read_text().split())
    pool = []
    for g in a.runs:
        for run in sorted(glob.glob(g)):
            for f in sorted(Path(run, 'logs').glob('*.json')):
                rec = json.loads(f.read_text(encoding='utf-8'))
                if rec.get('outcome') != 'correct' or rec['id'] in used or rec['id'] in drop:
                    continue
                reply = final_reply(rec)
                if reply:
                    pool.append((rec, reply))
    rng = random.Random(a.seed)
    rng.shuffle(pool)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    by_split, got = collections.defaultdict(list), collections.Counter()
    for rec, reply in pool:
        if rec['id'] in used:
            continue
        for kind in want:
            if got[kind] >= want[kind] or not eligible(kind, rec):
                continue
            forced = FORCE[kind](reply, rng)
            if forced:
                split = Path(rec['input']['split'])
                root = split.parent if (split.parent / 'manifest.jsonl').exists() else split   # unique worlds: the batch
                by_split[root].append({'id': rec['id'], 'kind': kind, 'replies': [forced], 'source': rec['run_id']})
                got[kind] += 1
                used.add(rec['id'])
                break
        if all(got[k] >= want[k] for k in want):
            break
    for root, rows in by_split.items():
        name = root.name
        with open(out / f'{name}.prefill.jsonl', 'w', encoding='utf-8') as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)
        (out / f'{name}.ids.txt').write_text(''.join(r['id'] + '\n' for r in rows))
        (out / f'{name}.split').write_text(str(root))
    print(dict(got), {r.name: len(v) for r, v in by_split.items()})


if __name__ == '__main__':
    main()
