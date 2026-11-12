"""How well datamate.rules.compare finds the changed rules of the synthetic rulebooks (no model calls).

Ground truth: gen.variants / gen.rulebook_gen record which standard lines each split edits (the old fragment of every
applied change). For each split rulebook: the standard lines whose meaning changed must leave the cookbook (`gone`)
and show in rulebook_changes ("missed" otherwise: the model would get the old recipe); standard lines of unchanged
meaning flagged as edited lose their recipe for nothing ("false edits").

python scripts/check_rule_changes.py [--old path/to/rules.py] [--show]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from datamate import rules  # noqa: E402
from gen import variants as V  # noqa: E402
from gen import rulebook_gen as RG  # noqa: E402


def pairs_of(names):
    out = []
    for n in names:
        if n in RG.EXTRA:
            out += RG.EXTRA[n][1]
        elif n in V.VARIANTS:
            out += V.VARIANTS[n][1]
    return out


def splits():
    for d in sorted((ROOT / 'data_gen').glob('rulevar_*')):
        if d.is_dir():
            name = d.name[len('rulevar_'):]
            yield f'rulevar/{name}', d / 'rulebook.md', [] if name == 'paraphrase' else [name]
    man = json.loads((ROOT / 'data_gen' / 'syn_v2' / 'manifest.json').read_text(encoding='utf-8'))
    for s, info in man['splits'].items():
        yield f'syn_v2/{s}', ROOT / 'data_gen' / 'syn_v2' / s / 'rulebook.md', info['parts'].get('variants', [])


def truth(train, text, names):
    """Standard keys whose line holds the old fragment of a change that this rulebook applied."""
    norm_lines = [rules.normalize(l) for l in text.splitlines()]
    out = set()
    for old, new in pairs_of(names):
        piece = max(new.split('|'), key=len).strip() if new else ''
        applied = not piece or any(rules.normalize(piece) in l for l in norm_lines)
        if not applied:
            continue
        out |= {k for k, line in train.items() if old.strip() and old.strip() in line}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', help='another rules.py to compare with (e.g. the committed one)')
    ap.add_argument('--show', action='store_true', help='print the false edits')
    a = ap.parse_args()
    mods = [('new', rules)]
    if a.old:
        spec = importlib.util.spec_from_file_location('rules_old', a.old)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        mods.append(('old', old))
    train = rules.load_train_units()
    total = {}
    print(f'{"split":32} {"ver":4} {"full":5} {"chg":>4} {"gone":>4} {"truth":>5} {"miss":>4} {"false":>5}')
    for name, path, names in splits():
        text = path.read_text(encoding='utf-8')
        t = truth(train, text, names)
        counterpart = {k for _, _, st, k in rules.align(text, train) if k}   # the rule is still in this rulebook
        for tag, mod in mods:
            c = mod.compare(text, train)
            gone = c['gone']
            missed = set() if c['full'] else t - gone           # full: the whole text is sent, nothing listed
            if c['full']:
                missed_full = t                                 # the cookbook keeps the old recipe of these
            else:
                missed_full = set()
            false = (gone - t) & counterpart                    # recipe dropped although the rule kept its meaning
            row = total.setdefault(tag, {'splits': 0, 'full': 0, 'truth': 0, 'missed': 0, 'missed_in_full': 0, 'false': 0})
            row['splits'] += 1; row['full'] += c['full']; row['truth'] += len(t); row['missed'] += len(missed)
            row['missed_in_full'] += len(missed_full); row['false'] += len(false)
            print(f'{name:32} {tag:4} {str(c["full"]):5} {len(c["changes"]):4} {len(gone):4} {len(t):5} '
                  f'{len(missed) + len(missed_full):4} {len(false):5}')
            if a.show and (false or missed):
                for k in sorted(false):
                    print('    false edit:', train[k][:150])
                for k in sorted(missed):
                    print('    MISSED    :', train[k][:150])
    print(json.dumps(total, ensure_ascii=False))


if __name__ == '__main__':
    main()
