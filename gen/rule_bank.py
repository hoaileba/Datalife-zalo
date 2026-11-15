"""Paraphrase bank of rulebook lines (gen/assets/rule_bank.json), made once: {line: [checked paraphrases]}.

gen.world_rules swaps each line it finds here for one of its paraphrases, so every world's rulebook is worded
differently while the meaning (and so the oracle gold) stays the one the code composed.

Lines: every rule line of gen.rulebook_gen.compose over all trades and many seeds (changed defaults included), and
the trade templates of gen.world_rules (placeholders {X} kept). Per batch of lines DeepSeek (thinking off, JSON)
writes K paraphrases; a paraphrase is kept only when
  - the mechanical checks pass: same table cell count, same numbers, same `code` spans, same §refs and {X}
    placeholders, same number of negations ('không');
  - a second call, shown only the original and the paraphrase, says they state the same rule (no condition added,
    dropped or changed).

  PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
  $PY -m gen.rule_bank --dry-run                       # lines collected, no model call
  $PY -m gen.rule_bank --k 4 --workers 8 --yes         # writes gen/assets/rule_bank.json (resumes: done lines skipped)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from gen import rulebook_gen as RG  # noqa: E402
from gen import world_rules as WR  # noqa: E402
from gen.industry_gen import _cost  # noqa: E402

LOG = WR.BANK.with_name('rule_bank.log.jsonl')


def collect(seeds=40):
    import yaml
    from gen.sim import TRAIN_META
    trades = list(TRAIN_META) + list(yaml.safe_load(
        (WR.BANK.with_name('new_industries.yaml')).read_text(encoding='utf-8')))
    seen = {}
    for s in range(seeds):
        rng = np.random.default_rng(s)
        for profile in ('train', 'mixed', 'reworded'):
            for inds in ([], [trades[s % len(trades)]]):
                c = RG.compose(inds, rng, profile)
                for ln in WR.lines(c.text):
                    seen.setdefault(ln, 0)
                    seen[ln] += 1
    for name in RG.STACKABLE:                       # every changed default once on its own
        c = RG.compose([], np.random.default_rng(0), 'train', force=[name])
        for ln in WR.lines(c.text):
            seen.setdefault(ln, 1)
    for rows, alts in WR.TEMPLATES.values():
        for r in list(rows) + [x for rr, _ in alts.values() for x in rr]:
            seen.setdefault(r, 1)
    return [ln for ln in seen if len(ln) >= 25 and _cells(ln) in (0, 2)]


# ---------------------------------------------------------------- checks
def _cells(ln):
    st = ln.strip()
    return len(st.strip('|').split('|')) if st.startswith('|') and st.endswith('|') else 0


def _sig(ln):
    return (_cells(ln), Counter(re.findall(r'\d+(?:[.,]\d+)?', ln)), Counter(re.findall(r'`[^`]+`', ln)),
            Counter(re.findall(r'§\s*\d+', ln)), Counter(re.findall(r'\{[A-Z]+\}', ln)),
            len(re.findall(r'(?i)\bkhông\b', ln)))


def mechanical(orig, para):
    if not isinstance(para, str) or not para.strip() or para.strip() == orig.strip() or '\n' in para.strip():
        return 'empty, same or several lines'
    a, b = _sig(orig), _sig(para)
    names = ('cells', 'numbers', 'code spans', '§refs', 'placeholders', 'negations')
    bad = [n for n, x, y in zip(names, a, b) if x != y]
    lead = lambda s: re.match(r'^\s*(?:[-*]\s+|\d+[.)]\s+)?', s).group(0).strip()
    if lead(orig) != lead(para):
        bad.append('line prefix (bullet)')
    if _cells(orig) and not para.strip().startswith('|'):
        bad.append('table row form')
    return ', '.join(bad)


GEN_SYSTEM = """You reword lines of a Vietnamese rulebook that defines how shop-data questions are answered. For every line give K paraphrases in natural Vietnamese that state EXACTLY the same rule:
- keep every condition, exception, inclusion/exclusion, number, date, rounding and "không" (same count of the word "không");
- keep `code spans`, §N references and {PLACEHOLDERS} verbatim; keep **bold** on the key terms;
- each line is one sentence group of plain text (no table pipes "|"); reply with one line per paraphrase;
- change wording and sentence order, not meaning; never add an example or a new case.
Reply with JSON: {"items": [{"i": <index>, "paraphrases": ["...", ...]}, ...]}"""

JUDGE_SYSTEM = """You check paraphrases of rulebook lines. For each pair say whether B states exactly the same rule as A: same conditions, same exceptions, same inclusions and exclusions, same numbers and rounding, nothing added, dropped, weakened or made ambiguous. Wording may differ.
Reply with JSON: {"items": [{"j": <index>, "same": true|false, "why": "<short>"}]}"""


def split_row(ln):
    """(name cell, rule cell) of a 2-cell table row; None for prose. Only the rule cell is reworded: the row is put
    back together by code, so the model never has to keep the table form."""
    st = ln.strip()
    if _cells(ln) == 2:
        name, rule = (c.strip() for c in st.strip('|').split('|'))
        return name, rule
    return None


def run_batch(llm, batch, k, log):
    texts = [split_row(ln)[1] if split_row(ln) else ln for ln in batch]
    msg = '\n'.join(f'[{i}] {x}' for i, x in enumerate(texts))
    r = llm.chat([{'role': 'system', 'content': GEN_SYSTEM.replace('K paraphrases', f'{k} paraphrases')},
                  {'role': 'user', 'content': f'K = {k}\n{msg}'}], response_format={'type': 'json_object'}, max_tokens=8000)
    cost = _cost(r.usage)
    try:
        items = {int(x['i']): x['paraphrases'] for x in json.loads(r.text)['items']}
    except Exception:          # noqa: BLE001
        items = {}
    cands = []
    for i, ln in enumerate(batch):
        row = split_row(ln)
        for p in items.get(i, []) or []:
            if row and isinstance(p, str):
                p = f'| {row[0]} | {p.strip().strip("|").strip()} |'
            why = mechanical(ln, p)
            if why:
                log({'line': ln, 'para': p, 'kept': False, 'why': why})
            else:
                cands.append((ln, p.strip()))
    kept = {}
    if cands:
        msg = '\n\n'.join(f'[{j}]\nA: {a}\nB: {b}' for j, (a, b) in enumerate(cands))
        r2 = llm.chat([{'role': 'system', 'content': JUDGE_SYSTEM}, {'role': 'user', 'content': msg}],
                      response_format={'type': 'json_object'}, max_tokens=8000)
        cost += _cost(r2.usage)
        try:
            verdict = {int(x['j']): (bool(x['same']), x.get('why', '')) for x in json.loads(r2.text)['items']}
        except Exception:      # noqa: BLE001
            verdict = {}
        for j, (a, b) in enumerate(cands):
            same, why = verdict.get(j, (False, 'no verdict'))
            log({'line': a, 'para': b, 'kept': same, 'why': why})
            if same:
                kept.setdefault(a, []).append(b)
    return kept, cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--k', type=int, default=4)
    ap.add_argument('--batch', type=int, default=8)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--config', default=str(ROOT / 'config.deepseek_direct_nothink.yaml'))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--yes', action='store_true')
    a = ap.parse_args()
    todo = collect()
    bank = WR.load_bank()
    todo = [ln for ln in todo if ln not in bank]
    batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    print(f'{len(todo)} lines to reword ({len(bank)} already in the bank), {len(batches)} batches, about '
          f'${len(batches) * 0.004:.2f}')
    if a.dry_run:
        for ln in todo[:15]:
            print('  ', ln[:150])
        return
    if not a.yes:
        raise SystemExit('model calls need --yes (approved by the user)')
    from gen.industry_gen import make_llm
    llm = make_llm(a.config, temperature=0.7, max_concurrency=a.workers, timeout_seconds=300)
    lock = threading.Lock()
    total = [0.0]

    def log(row):
        with lock, open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    def job(b):
        try:
            kept, c = run_batch(llm, b, a.k, log)
        except Exception as exc:   # noqa: BLE001
            log({'error': f'{type(exc).__name__}: {exc}'[:300]})
            return
        with lock:
            total[0] += c
            for ln, ps in kept.items():
                bank.setdefault(ln, [])
                bank[ln] += [p for p in ps if p not in bank[ln]]
            tmp = WR.BANK.with_suffix('.tmp')
            tmp.write_text(json.dumps(bank, ensure_ascii=False, indent=1), encoding='utf-8')
            tmp.replace(WR.BANK)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(job, batches))
    n = sum(len(v) for v in bank.values())
    print(f'bank: {len(bank)} lines, {n} paraphrases; ${total[0]:.3f}')


if __name__ == '__main__':
    main()
