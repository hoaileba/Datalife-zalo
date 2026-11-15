"""Code-format compliance of a run's answer programs (docs/CODE_FORMAT.md §5): for SFT filtering and measurement,
never applied at run time. Counts per program: shop column names written outside the BIND block, columns bound
without kit.name, one- or two-letter variable names, missing block comments; lambda / merge / agg are only counted.

PYTHONPATH=src python scripts/check_code_style.py outputs/runs/<run> [--split data/train]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from datamate.data import load_business  # noqa: E402
from datamate.helpers import norm  # noqa: E402

BLOCK = re.compile(r'^#\s*([123])\.\s*(BIND|COMPUTE|CHECK)', re.I | re.M)


def check(code, columns):
    """Issues of one program (a list of short tags) given the shop's column names."""
    issues = []
    marks = {int(m.group(1)): code[:m.start()].count('\n') + 1 for m in BLOCK.finditer(code)}
    if set(marks) != {1, 2, 3}:
        issues.append('block_comments')
    bind_end = marks.get(2, 0)
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return issues + ['syntax']
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    if any(len(n) <= 2 for n in names):
        issues.append('short_names')
    cols = {norm(c) for c in columns}
    literals = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and norm(n.value) in cols]
    if bind_end and any(n.lineno >= bind_end for n in literals):
        issues.append('column_outside_bind')
    bound = [n for n in literals if n.lineno < bind_end] if bind_end else []
    via_name = {id(a) for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, 'attr', '') == 'name'
                for a in c.args if isinstance(a, ast.Constant)}
    if any(id(n) not in via_name for n in bound):
        issues.append('bound_without_kit_name')
    for tag, pat in (('lambda', r'\blambda\b'), ('merge', r'\.merge\('), ('agg', r'\.agg\(')):
        if re.search(pat, code):
            issues.append('uses_' + tag)
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run')
    ap.add_argument('--split', help='split folder (default: from summary.json)')
    a = ap.parse_args()
    run = Path(a.run)
    summary = json.loads((run / 'summary.json').read_text()) if (run / 'summary.json').exists() else {}
    default = a.split or summary.get('split')
    shops, counts, programs = {}, Counter(), 0
    for f in sorted((run / 'logs').glob('q*.json')):
        log = json.loads(f.read_text(encoding='utf-8'))
        b = log['business_id']
        split = Path(default or (log.get('input') or {}).get('split'))    # teacher records: each its own split
        split = split if split.is_absolute() else ROOT / split
        if b not in shops:
            biz = load_business(split / 'data' / b, split / 'calendar.csv', ROOT / 'outputs' / 'cache')
            shops[b] = [str(c) for t in biz.tables.values() for c in t.columns]
        for e in log.get('trace', []):
            if e.get('event') == 'execution' and not e.get('explore'):
                programs += 1
                counts.update(check(e['code'], shops[b]))
    print(json.dumps({'programs': programs, **{k: f'{v}/{programs}' for k, v in sorted(counts.items())}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
