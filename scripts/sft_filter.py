"""Drop known-bad records from a gen.package folder; writes a new package folder (same files, same format).

Reasons (a record = every sample of one teacher record: run + question id):
  zero_rule   the trajectory went through the old all-zero check (removed 12/11, commit 7b44ede): its later turns
              teach a behaviour the agent no longer has (re-checking a 0 with a second program)
  ids         question ids given with --drop-ids (e.g. records found to rest on a wrong gold)
  stale_label reskin records whose reply still cites (quoted or as a list item) a label of the ORIGINAL shop that the renamed copy no longer has
              (a value listed in the original catalog, absent from the copy's whole prompt)
  run         (--drop-runs) every record of a teacher run whose name starts with one of the given prefixes
              (e.g. reskin: keep the original train shops only)
  other_skin  (--one-skin) the same train question on another shop copy: each train question once, on one copy
  weak        (--strict) an answer (not "unanswerable") given without running any program (gen.sft flag no_program):
              right by luck or from the lookup alone. Unanswerable, boolean and zero answers are kept: they are the
              rare behaviours the student must learn

No model calls.  python scripts/sft_filter.py --package outputs/sft/final_full --out outputs/sft/final_clean \
                     --drop-ids q_t2_00489,q_t1_00531 [--strict]
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZERO_MARKS = ('every numeric value is 0', 'zero_confirmed')
VALUES = re.compile(r'values: (.*)$')


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def user_text(sample):
    return '\n'.join(m['content'] for m in sample['prompt'] if m['role'] == 'user')


def catalog_values(text):
    """Text values the catalog lists ("values: a ×12; b ×3")."""
    out = set()
    for line in text.splitlines():
        m = VALUES.search(line)
        if m:
            for part in m.group(1).split('; '):
                v = re.sub(r'\s×\d+$', '', part).strip()
                if len(v) >= 3 and re.search(r'[^\W\d_]', v):
                    out.add(v)
    return out


def names(text, value):
    return re.search(r'(?<!\w)' + re.escape(value.lower()) + r'(?!\w)', text.lower()) is not None


OPEN, CLOSE = '[\'"“‘`(\\[]|,', '[\'"”’`)\\],]'


def cites(text, value):
    """The reply cites the value as a label: quoted, or an item of a bracketed / comma list ("(a, b)", "[a, b]").
    A bare occurrence is ordinary text ("không bị trả hàng" is not the label "trả hàng")."""
    return re.search(f'(?:{OPEN})\\s*{re.escape(value.lower())}\\s*{CLOSE}', text.lower()) is not None


def record_key(meta):
    return meta['run'], meta['id']


def restamp(folder, note):
    """stats.json of a derived package: sample counts and file hashes of the files now in the folder (gen.validate
    checks both); `note` records what was derived. Lengths/distributions stay those of the parent package."""
    import hashlib
    folder = Path(folder)
    stats = json.loads((folder / 'stats.json').read_text(encoding='utf-8'))
    for side in ('train', 'val'):
        if (folder / f'{side}_meta.jsonl').exists():
            metas = read_jsonl(folder / f'{side}_meta.jsonl')
            stats['samples'][side] = len(metas)
            stats['samples'][f'{side}_final'] = sum(1 for m in metas if m.get('final'))
    stats['files'] = {f.name: {'bytes': f.stat().st_size, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
                      for f in sorted(folder.iterdir()) if f.is_file() and f.name != 'stats.json'}
    stats.setdefault('derived', []).append(note)
    (folder / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--package')
    ap.add_argument('--restamp', metavar='FOLDER', help='only refresh stats.json of a derived package (e.g. sft_mix select output)')
    ap.add_argument('--out')
    ap.add_argument('--drop-ids', default='')
    ap.add_argument('--drop-runs', default='', help='comma list of run-name prefixes to drop entirely (e.g. reskin)')
    ap.add_argument('--strict', action='store_true', help='also drop answers given without any program (not unanswerable)')
    ap.add_argument('--one-skin', action='store_true', help='train side: one record per train question, on ONE shop copy '
                    '(original, reskin_1 or reskin_2, rotated by a hash of the id among the clean copies)')
    ap.add_argument('--teacher-root', default=str(ROOT / 'outputs' / 'teacher'))
    a = ap.parse_args()
    if a.restamp:
        return restamp(a.restamp, {'by': 'sft_mix select', 'from': 'see mix_stats.json'})
    pkg, out = Path(a.package), Path(a.out)
    drop_ids = {x for x in a.drop_ids.split(',') if x}
    drop_runs = tuple(x for x in a.drop_runs.split(',') if x)
    parts = {name: (read_jsonl(pkg / f'{name}.jsonl'), read_jsonl(pkg / f'{name}_meta.jsonl')) for name in ('train', 'val')
             if (pkg / f'{name}.jsonl').exists()}
    for name, (rows, metas) in parts.items():
        if len(rows) != len(metas) or any(r['id'] != m['key'] for r, m in zip(rows, metas)):
            raise SystemExit(f'{name}.jsonl and {name}_meta.jsonl disagree')

    # original-shop prompts (train_v1) by question id: the labels a reskin copy must not name any more
    original = {}
    for rows, metas in parts.values():
        for r, m in zip(rows, metas):
            if m['run'] == 'train_v1' and m['id'] not in original:
                original[m['id']] = catalog_values(user_text(r))

    reasons, zero_cache = {}, {}
    for rows, metas in parts.values():
        for r, m in zip(rows, metas):
            key = record_key(m)
            if key in reasons:
                continue
            why = None
            if drop_runs and m['run'].startswith(drop_runs):
                why = 'run'
            elif m['id'] in drop_ids:
                why = 'ids'
            if why is None:
                if key not in zero_cache:
                    log = Path(a.teacher_root) / m['run'] / m['record']
                    text = log.read_text(encoding='utf-8') if log.exists() else ''
                    zero_cache[key] = any(z in text for z in ZERO_MARKS)
                if zero_cache[key]:
                    why = 'zero_rule'
            if why is None and m['run'].startswith('reskin') and m['id'] in original:
                prompt = user_text(r).lower()
                old = [v for v in original[m['id']] - catalog_values(user_text(r)) if not names(prompt, v)]
                if any(cites(r['completion'][0]['content'], v) for v in old):
                    why = 'stale_label'
            if why is None and a.strict and 'no_program' in m['weak'] and 'unanswerable' not in m['weak']:
                why = 'weak'
            if why:
                reasons[key] = why

    if a.one_skin and 'train' in parts:                  # the train side keeps one shop copy per train question
        import hashlib
        copies = collections.defaultdict(list)
        for m in parts['train'][1]:
            if m['final'] and record_key(m) not in reasons and (m['run'] == 'train_v1' or m['run'].startswith('reskin')):
                copies[m['id']].append(m['run'])
        for qid, runs in copies.items():
            runs = sorted(set(runs))
            keep = runs[int(hashlib.sha256(qid.encode()).hexdigest(), 16) % len(runs)]
            for r in runs:
                if r != keep:
                    reasons[(r, qid)] = 'other_skin'
    out.mkdir(parents=True, exist_ok=True)
    for f in pkg.iterdir():                               # README, stats, val_questions, sft_lora.py ...
        if f.is_file() and not re.fullmatch(r'(train|val)(_meta)?\.jsonl', f.name):
            shutil.copy2(f, out / f.name)
    counts = collections.Counter()
    for name, (rows, metas) in parts.items():
        keep = [(r, m) for r, m in zip(rows, metas) if record_key(m) not in reasons]
        for r, m in zip(rows, metas):
            if record_key(m) in reasons:
                counts[f'{name}:{reasons[record_key(m)]}'] += 1
        write_jsonl(out / f'{name}.jsonl', [r for r, _ in keep])
        write_jsonl(out / f'{name}_meta.jsonl', [m for _, m in keep])
        counts[f'{name}:kept'] = len(keep)
    report = {'package': str(pkg), 'drop_ids': sorted(drop_ids), 'drop_runs': list(drop_runs), 'strict': a.strict,
              'dropped_records': dict(collections.Counter(reasons.values())), 'samples': dict(counts),
              'records': sorted(f'{k[0]}/{k[1]}\t{v}' for k, v in reasons.items())}
    (out / 'filtered.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    restamp(out, {'by': 'scripts/sft_filter.py', 'from': str(pkg), 'dropped_records': report['dropped_records']})
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
