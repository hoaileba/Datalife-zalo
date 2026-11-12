"""Final SFT data plan: which pools the teacher runs on (plan) and which samples go into training (select).

No model or API calls. Re-runnable: everything is computed from the current splits and packages, by rule.

  plan    reads the question pools (data/train, data_gen/rulevar_*, data_gen/syn_v2/*, data_gen/train_aug),
          writes <out>/gen_plan.json (pools, counts, coverage, sha256 of questions.jsonl, priority, cost) and
          <out>/run_teacher.sh (the teacher commands, NOT run here; each one resumable with --resume).
  select  reads ONE full package built by gen.package from every usable run (--per-group 3, see run_teacher.sh)
          and writes a training subset of --budget samples: pools by share, strata by intent, one shop skin per
          question first, rare behaviours first, held-out data never selected (checked). val files are copied.

PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
$PY scripts/sft_mix.py plan --out outputs/sft_plan
$PY scripts/sft_mix.py select --package outputs/sft/final_full --budget 5000 --out outputs/sft/final_5k

Pools (from the sample's split):
  std   data/train and data_gen/reskin_<k> (train shops, standard rulebook; reskin = same solution on renamed files)
  rule  data_gen/rulevar_<variant> (5 calibrated train shops, one rulebook change per split)
  syn   data_gen/syn_v2/t1..t7 (synthetic shops, 6 new industries, t1 standard rules + industry sections, t2-t7 changed)
  never data_gen/syn_v2/val, data_gen/train_aug (near-duplicates of train: same shop, as_of and gold), private_mock*,
        any test split, and any run whose name starts with try/demo/smoke (stale gold after the 12/11 generator fixes)
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = '/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python'

# ---- pools -------------------------------------------------------------------------------------------------------
SYN_TRAIN = ['t1', 't2', 't3', 't4', 't5', 't6', 't7']
VAL_INDUSTRIES = ['hotpot', 'spa_salon']          # syn_v2/val (manifest.json: val.industries)
VAL_FAMILIES = ['P']                              # syn_v2/val + 2 shops of t5 (held-out family on seen industries)
VAL_SHOPS = ['biz_108', 'biz_110', 'biz_130']     # gen.package default: train shops held out (and all their skins)
SKIP_RUN = re.compile(r'^(try|demo|smoke|train_aug|aug)')
# REAL DeepSeek prices (USD / 1M: miss, hit, output): fitted on train_v1's balance drop (9.03 -> 2.81 = 6.22 USD for
# 1.7M miss, 50.7M hit, 10.2M output tokens: 0.28/0.028/0.42 gives 6.18). The old 0.07,0.007,0.28 underestimated ~1.9x.
PRICE = '0.28,0.028,0.42'
USD_PER_Q = {'rule': 0.0032, 'syn': 0.0032, 'val': 0.0030, 'aug': 0.0021}    # try100 / train_v1 token use x real prices
SEC_PER_Q_16 = 1.2                                # train_v1: 3000 q in 3583 s at 16 workers (rule/syn ~1.3x longer)

# shares of the training budget (samples) per pool; linear in between, flat outside
# (syn grows with the budget: std is ~2700 distinct questions, extra std budget only buys second shop skins)
SHARES = {3000: {'std': 0.55, 'rule': 0.15, 'syn': 0.30},
          5000: {'std': 0.48, 'rule': 0.17, 'syn': 0.35},
          8000: {'std': 0.40, 'rule': 0.18, 'syn': 0.42}}
RETRY_REASONS = ('llm_error', 'host_error')       # gen.teacher: records --resume runs again (not done)
SPILL = ('syn', 'rule', 'std')                    # a pool short of samples gives its quota to these, in this order
REPAIR = {'recovered', 'three_calls', 'zero'}     # multi-turn repair behaviours: first in every pool
ALPHA = {'std': 0.7, 'rule': 0.5, 'syn': 0.5}     # stratum weight = size**alpha (1 = proportional, 0 = uniform)
PARAPHRASE_MAX = 0.12                             # rulevar_paraphrase: at most this share of the rule pool
MAX_PER_GROUP = 3                                 # records of one train question across std + unchanged rule
UNCHANGED_SHARE = 0.18                            # other rulevar answers the change does not move: this share
RARE = ('recovered', 'unanswerable', 'no_program', 'zero', 'three_calls')     # not boolean: a coin flip


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def hfrac(*parts):
    return int(hashlib.sha1(':'.join(map(str, parts)).encode()).hexdigest()[:12], 16) / float(1 << 48)


def pool_of(split: str):
    s = split.replace('\\', '/').rstrip('/')
    if 'public_test' in s or 'private' in s:
        return 'forbidden'
    if s == 'data/train' or re.search(r'data_gen/reskin_\d+$', s):
        return 'std'
    if re.search(r'data_gen/rulevar_[a-z_]+$', s):
        return 'rule'
    m = re.search(r'data_gen/syn_v2/(\w+)$', s)
    if m:
        return 'syn' if m.group(1) in SYN_TRAIN else 'never'
    return 'never'


def shares(budget):
    keys = sorted(SHARES)
    if budget <= keys[0]:
        return dict(SHARES[keys[0]])
    if budget >= keys[-1]:
        return dict(SHARES[keys[-1]])
    for a, b in zip(keys, keys[1:]):
        if a <= budget <= b:
            w = (budget - a) / (b - a)
            return {p: SHARES[a][p] * (1 - w) + SHARES[b][p] * w for p in SHARES[a]}


def fingerprint(path: Path):
    """sha256 over the files that decide a record's gold and prompt: questions, answers, meta, rulebook, calendar,
    and the data tree behind the (symlinked) data/ folder (relative names, sizes, mtimes)."""
    h = hashlib.sha256()
    for name in ('questions.jsonl', 'answers.jsonl', 'meta.jsonl', 'rulebook.md', 'calendar.csv'):
        f = path / name
        h.update(f'{name}:{sha256(f) if f.exists() else "-"}\n'.encode())
    data = Path(os.path.realpath(path / 'data'))
    h.update(f'data:{data}\n'.encode())
    for dirpath, dirnames, filenames in os.walk(data, followlinks=True):
        dirnames.sort()
        for fn in sorted(filenames):
            f = Path(dirpath) / fn
            st = f.stat()
            h.update(f'{f.relative_to(data)}:{st.st_size}:{st.st_mtime_ns}\n'.encode())
    return h.hexdigest()


def spent(plan_rows):
    total = 0.0
    for r in plan_rows:
        idx = ROOT / r['run'] / 'index.jsonl'
        if idx.exists():
            total += sum(x.get('cost_usd') or 0 for x in read_jsonl(idx))
    return total


def load_plan(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check(a):
    """Before a teacher command: the split is the one planned, and the stage has budget left. Exit 1 otherwise."""
    gp = load_plan(a.plan)
    row = next((r for r in gp['splits'] if r['path'] == a.split), None)
    if row is None:
        raise SystemExit(f'{a.split}: not in {a.plan}')
    fp_now = fingerprint(ROOT / a.split)
    if fp_now != row['fingerprint']:
        raise SystemExit(f'{a.split}: changed since the plan ({row["fingerprint"][:12]} -> {fp_now[:12]}). Stop: a resumed '
                         f'run would mix records of two versions. Re-plan and use a new --out (or delete {a.run}).')
    usd = spent(gp['splits'])
    if usd >= gp['total_max_usd']:
        raise SystemExit(f'stage budget reached: {usd:.2f} >= {gp["total_max_usd"]} USD (raise total_max_usd in {a.plan} to go on)')
    print(f'{a.split}: unchanged; spent so far {usd:.2f} / {gp["total_max_usd"]} USD')


def gate(a):
    """After the teacher stage: every planned run complete and on the planned split version; accuracy per split and
    per (split, intent). Writes gate.json (+ gate_runs.txt = training runs that pass). Exit 1 when a run is missing,
    incomplete or stale (--allow-incomplete to package what exists)."""
    gp = load_plan(a.plan)
    out = Path(a.plan).parent
    report, runs_ok, drop_intents, problems = [], [], [], []
    pooled, intent_splits = collections.defaultdict(lambda: [0, 0]), collections.defaultdict(set)
    for r in gp['splits']:
        idx = ROOT / r['run'] / 'index.jsonl'
        recs = read_jsonl(idx) if idx.exists() else []
        last = {}
        for x in recs:                                     # a resumed record appears again: keep the last line
            last[x['id']] = x
        recs = list(last.values())
        stale = fingerprint(ROOT / r['path']) != r['fingerprint']
        retry = sum(1 for x in recs if x.get('reason') in RETRY_REASONS)      # API down / balance out / host bug
        recs = [x for x in recs if x.get('reason') not in RETRY_REASONS]
        done = sum(1 for x in recs if x.get('outcome') in ('correct', 'wrong', 'abstain'))
        abstain = sum(1 for x in recs if x.get('outcome') == 'abstain')
        ok = sum(1 for x in recs if x.get('outcome') == 'correct')
        rate = ok / done if done else 0.0
        meta = {m['id']: m for m in read_jsonl(ROOT / r['path'] / 'meta.jsonl')} if (ROOT / r['path'] / 'meta.jsonl').exists() else {}
        by_int = collections.defaultdict(lambda: [0, 0])
        for x in recs:
            if x.get('outcome') in ('correct', 'wrong', 'abstain'):
                k = (meta.get(x['id']) or {}).get('intent') or 'unknown'
                by_int[k][0] += 1
                by_int[k][1] += x.get('outcome') == 'correct'
                if r['pool'] in ('syn', 'rule'):
                    pooled[(r['pool'], k)][0] += 1
                    pooled[(r['pool'], k)][1] += x.get('outcome') == 'correct'
                    intent_splits[(r['pool'], k)].add(r['path'])
        weak = {k: f'{v[1]}/{v[0]}' for k, v in by_int.items() if v[0] >= a.min_n and v[1] / v[0] < a.min_rate}
        row = {'run': r['run'], 'split': r['path'], 'pool': r['pool'], 'planned': r['questions'], 'done': done,
               'correct': ok, 'rate': round(rate, 3), 'abstain': abstain, 'retry_reason_records': retry, 'stale': stale,
               'weak_intents': weak}
        report.append(row)
        if stale:
            problems.append(f"{r['path']}: split changed after the plan")
        if done < r['questions']:
            problems.append(('note: ' if r['pool'] == 'val' else '') + f"{r['run']}: {done}/{r['questions']} done"
                            + (f" ({retry} ended on llm_error/host_error: run stage 1 again, it resumes them)" if retry else ''))
        if done and abstain / done > a.max_abstain and r['pool'] != 'val':
            problems.append(f"{r['run']}: {abstain}/{done} abstain > {a.max_abstain:.0%}: read a few records first")
        if r['pool'] in ('syn', 'rule') and done and not stale:
            if rate >= a.min_rate:
                runs_ok.append(r['run'])
                drop_intents += [[r['path'], k] for k in weak]
            else:
                problems.append(('note: ' if a.allow_drop else '') +
                                f"{r['run']}: {rate:.0%} correct < {a.min_rate:.0%}: whole split left out of the package"
                                + ('' if a.allow_drop else ' (pass --allow-drop to accept)'))
        print(f"{r['run']:45s} {done:4d}/{r['questions']:4d} correct {rate:6.1%} {'STALE ' if stale else ''}"
              f"weak intents {weak if weak else '-'}")
    for (pool, k), (n, c) in sorted(pooled.items()):            # an intent weak on every split, few per split
        if n >= a.min_n and c / n < a.min_rate:
            for sp in sorted(intent_splits[(pool, k)]):
                if [sp, k] not in drop_intents:
                    drop_intents.append([sp, k])
            print(f'pooled weak intent {pool}:{k} {c}/{n}: dropped on every split')
    res = {'created_at': dt.datetime.now().isoformat(timespec='seconds'), 'runs': report, 'train_runs': runs_ok,
           'drop_intents': drop_intents, 'problems': problems, 'spent_usd': round(spent(gp['splits']), 3),
           'min_rate': a.min_rate, 'min_n': a.min_n}
    (out / 'gate.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'gate_runs.txt').write_text(' '.join(runs_ok) + '\n', encoding='utf-8')
    print(f"spent {res['spent_usd']} USD; {len(runs_ok)} training runs pass; {len(drop_intents)} (split, intent) dropped")
    hard = [p for p in problems if not p.startswith('note:') and not (a.allow_incomplete and ' done' in p)]
    if hard:
        raise SystemExit('gate failed:\n' + '\n'.join(hard))


# ---- plan --------------------------------------------------------------------------------------------------------
def split_summary(path: Path):
    qs = read_jsonl(path / 'questions.jsonl')
    ans = {a['id']: a for a in read_jsonl(path / 'answers.jsonl')} if (path / 'answers.jsonl').exists() else {}
    meta = {m['id']: m for m in read_jsonl(path / 'meta.jsonl')} if (path / 'meta.jsonl').exists() else {}
    types = collections.Counter((ans.get(q['id']) or {}).get('type') for q in qs)
    intents = collections.Counter((meta.get(q['id']) or {}).get('intent') for q in qs) if meta else None
    out = {'path': str(path.relative_to(ROOT)), 'questions': len(qs), 'shops': len({q['business_id'] for q in qs}),
           'sha256': sha256(path / 'questions.jsonl'), 'fingerprint': fingerprint(path),
           'mtime': dt.datetime.fromtimestamp((path / 'questions.jsonl').stat().st_mtime).isoformat(timespec='seconds'),
           'gold_types': dict(types.most_common())}
    if intents:
        out['intents'] = len(intents)
        out['top_intent_share'] = round(intents.most_common(1)[0][1] / len(qs), 3)
        out['top_intents'] = intents.most_common(5)
    if meta:
        m = list(meta.values())
        if 'changed' in m[0]:
            out['changed'] = sum(1 for x in m if x.get('changed'))
            out['source'] = dict(collections.Counter(x.get('source') for x in m))
        if 'moved' in m[0]:
            out['moved'] = sum(1 for x in m if x.get('moved'))
            out['industries'] = dict(collections.Counter(x.get('industry') for x in m).most_common())
            out['families'] = dict(collections.Counter(x.get('family') for x in m).most_common())
    zero = sum(1 for a in ans.values() if isinstance(a.get('answer'), (int, float)) and not isinstance(a.get('answer'), bool)
               and a['answer'] == 0)
    out['zero_answers'] = zero
    return out


def plan(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pools = []
    # priority: new industries (certain in private) > rulebook changes on real shops > eval reference > nothing else
    for s in SYN_TRAIN:
        pools.append(('syn', ROOT / 'data_gen' / 'syn_v2' / s, 1, f'syn_v2_{s}'))
    for p in sorted((ROOT / 'data_gen').glob('rulevar_*')):
        if p.is_dir():
            pools.append(('rule', p, 2, p.name))
    pools.append(('val', ROOT / 'data_gen' / 'syn_v2' / 'val', 3, 'syn_v2_val'))
    plan_rows, skipped = [], []
    for kind, path, prio, run in pools:
        if not (path / 'questions.jsonl').exists():
            skipped.append({'path': str(path), 'why': 'no questions.jsonl'})
            continue
        s = split_summary(path)
        s.update({'pool': kind, 'priority': prio, 'run': f'outputs/teacher/{run}',
                  'est_usd': round(s['questions'] * USD_PER_Q[kind], 2),
                  'est_minutes_16w': round(s['questions'] * SEC_PER_Q_16 * 1.3 / 60, 1)})
        if (ROOT / s['run'] / 'logs').exists():
            s['note'] = 'run folder exists: resume it (--resume) or pick a new --out; do not mix with try100 runs'
        plan_rows.append(s)
    aug = ROOT / 'data_gen' / 'train_aug'
    aug_info = split_summary(aug) if (aug / 'questions.jsonl').exists() else None
    if aug_info:
        aug_info.update({'pool': 'aug', 'priority': None, 'decision': 'skip',
                         'why': 'same shop, as_of and gold as a train question (noise or template rewrite): the teacher '
                                'program would be the same; the group cap in select would drop it anyway; '
                                'train_v1 + 2 reskins already give 3 records per question'})
    tot_q = sum(r['questions'] for r in plan_rows)
    gen = {'created_at': dt.datetime.now().isoformat(timespec='seconds'),
           'teacher': 'deepseek-flash (config.deepseek_direct.yaml)',
           'splits': plan_rows, 'skipped': skipped, 'train_aug': aug_info,
           'totals': {'questions': tot_q, 'est_usd': round(sum(r['est_usd'] for r in plan_rows), 2),
                      'est_hours_16w': round(sum(r['est_minutes_16w'] for r in plan_rows) / 60, 2),
                      'by_priority': {p: sum(r['questions'] for r in plan_rows if r['priority'] == p) for p in (1, 2, 3)}},
           'existing_runs_used': ['outputs/teacher/train_v1', 'outputs/teacher/reskin_1', 'outputs/teacher/reskin_2'],
           'existing_runs_not_used': 'try100_*, demo_*, smoke, try6: gold of rulevar/syn changed with the 12/11 fixes; '
                                     'the final run re-asks the same ids'}
    gen['total_max_usd'] = round(max(12.0, gen['totals']['est_usd'] * 1.4), 1)
    (out / 'gen_plan.json').write_text(json.dumps(gen, ensure_ascii=False, indent=1), encoding='utf-8')
    plan_rel = os.path.relpath(out / 'gen_plan.json', ROOT)
    head = ['#!/usr/bin/env bash', 'set -euo pipefail', f'PY={PY}', 'export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.',
            'export DEEPSEEK_BASE_URL=${DEEPSEEK_BASE_URL:-https://api.deepseek.com}   # unset: client falls back to 127.0.0.1:8000 and hangs',
            'cd ' + str(ROOT), f'PRICE={PRICE}', f'PLAN={plan_rel}', '']
    lines = ['#!/usr/bin/env bash',
             "# STAGE 1: final teacher run (DeepSeek flash). NOT run by sft_mix.py. Needs the user's approval and balance.",
             f'# {tot_q} questions, est. {gen["totals"]["est_usd"]} USD, ~{gen["totals"]["est_hours_16w"]} h at 16 workers;'
             f' the whole stage stops once {gen["total_max_usd"]} USD are spent (sum over the planned runs).',
             '# Before: commit src/ gen/ data_gen/ (frozen); prompts are rebuilt by gen.package with the code at package time.',
             '# Interrupted / budget stop / API down: run this script again (each command resumes; done records are skipped,',
             '# llm_error/host_error re-run). Each split is checked against its fingerprint in gen_plan.json first: a split',
             '# regenerated after the plan (questions, gold, meta, rulebook or data files) stops the script.',
             '# Order = priority: syn_v2 t1..t7, rulevar_*, syn_v2/val.'] + head[1:]
    for r in sorted(plan_rows, key=lambda r: (r['priority'], r['path'])):
        cap = max(0.3, round(r['est_usd'] * 2.0, 1))
        lines.append(f"# p{r['priority']} {r['pool']}: {r['questions']} q, est. {r['est_usd']} USD")
        lines.append(f"$PY scripts/sft_mix.py check --plan $PLAN --split {r['path']} --run {r['run']}")
        lines.append(f"R=; [ -d {r['run']}/logs ] && R=--resume")
        lines.append(f"$PY -m gen.teacher --split {r['path']} --out {r['run']} --config config.deepseek_direct.yaml --all "
                     f"--workers 16 --concurrency 16 --price $PRICE --max-usd {cap} --yes $R")
    lines += ['', 'echo "STAGE 1 done: now run package_and_select.sh"']
    (out / 'run_teacher.sh').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    runs = ' '.join(['outputs/teacher/train_v1', 'outputs/teacher/reskin_1', 'outputs/teacher/reskin_2'] +
                    ['$(cat ' + os.path.relpath(out / 'gate_runs.txt', ROOT) + ')'])
    pk = ['#!/usr/bin/env bash', '# STAGE 2: gate, ONE full package, validate, training subsets. No model calls.'] + head[1:] + [
        '# gate: every planned run complete and unchanged; teacher accuracy per split / intent; writes gate.json',
        '# (splits < 70 % correct are left out of gate_runs.txt, intents < 70 % are dropped by select). Exit 1 = stop.',
        f'$PY scripts/sft_mix.py gate --plan $PLAN',
        'for r in ' + ' '.join(r['run'] for r in plan_rows) + '; do [ -d $r ] && $PY -m gen.teacher_stats $r --price $PRICE || true; done',
        '# full package: every record of every skin; held-out shops / industries / family go to val',
        f'$PY -m gen.package --teacher {runs} --out outputs/sft/final_full --per-group 3 --require-exact '
        f'--val-shops {",".join(VAL_SHOPS)} --val-industries {",".join(VAL_INDUSTRIES)} --val-families {",".join(VAL_FAMILIES)}',
        '$PY -m gen.validate outputs/sft/final_full --rebuild --replay',
        '# training subsets (pick the one that fits the GPU budget)',
        'for b in 3000 5000 8000; do $PY scripts/sft_mix.py select --package outputs/sft/final_full --budget $b '
        f'--gate {os.path.relpath(out / "gate.json", ROOT)} --out outputs/sft/final_${{b}}; done']
    (out / 'package_and_select.sh').write_text('\n'.join(pk) + '\n', encoding='utf-8')
    print(json.dumps(gen['totals'], indent=1))
    for r in plan_rows:
        print(f"p{r['priority']} {r['pool']:4s} {r['path']:45s} q={r['questions']:5d} shops={r['shops']:2d} "
              f"intents={r.get('intents')} top={r.get('top_intent_share')} changed={r.get('changed', r.get('moved'))} "
              f"usd={r['est_usd']} {r['mtime']}")
    if aug_info:
        print(f"skip train_aug: {aug_info['questions']} q ({aug_info['why'][:60]}...)")
    print(f'wrote {out}/gen_plan.json, {out}/run_teacher.sh, {out}/package_and_select.sh')


# ---- select ------------------------------------------------------------------------------------------------------
class Rec:
    """One teacher record of the package = all its samples (explore turns + final turn); the unit of selection."""

    def __init__(self, key):
        self.key, self.samples, self.metas = key, [], []

    @property
    def m(self):
        return next((x for x in self.metas if x.get('final')), self.metas[0])

    def flags(self):
        f = set()
        for x in self.metas:
            if x.get('recovered'):
                f.add('recovered')
            for w in x.get('weak') or []:
                f.add(w)
        if (self.m.get('calls') or 0) >= 3:
            f.add('three_calls')
        return f & set(RARE)


def water_fill(sizes, quota, alpha):
    """Targets per stratum (in samples): weight size**alpha, never above the stratum size, leftovers re-spread."""
    target = {k: 0.0 for k in sizes}
    left, open_ = float(quota), {k for k, v in sizes.items() if v > 0}
    while left > 1e-6 and open_:
        w = {k: sizes[k] ** alpha for k in open_}
        tw = sum(w.values())
        spill = 0.0
        for k in list(open_):
            add = left * w[k] / tw
            room = sizes[k] - target[k]
            if add >= room:
                target[k] = sizes[k]
                spill += add - room
                open_.discard(k)
            else:
                target[k] += add
        left = spill
    return target


def take(strata, quota, alpha, chosen, seed, tag):
    """Fill `quota` samples from {stratum: [Rec]} (records already ordered by priority inside a stratum)."""
    sizes = {k: sum(len(r.samples) for r in v if r.key not in chosen) for k, v in strata.items()}
    target = water_fill(sizes, quota, alpha)
    got = 0
    for k in sorted(strata):
        have = 0
        for r in strata[k]:
            if r.key in chosen:
                continue
            if have + len(r.samples) / 2 > target[k]:      # rounding: take when at least half of it fits
                break
            chosen[r.key] = tag
            have += len(r.samples)
        got += have
    return got


def select(a):
    pkg, out = Path(a.package), Path(a.out)
    if out.resolve() == pkg.resolve():
        raise SystemExit('--out must differ from --package')
    metas = read_jsonl(pkg / 'train_meta.jsonl')
    vmetas = read_jsonl(pkg / 'val_meta.jsonl') if (pkg / 'val_meta.jsonl').exists() else []
    vq = read_jsonl(pkg / 'val_questions.jsonl') if (pkg / 'val_questions.jsonl').exists() else []
    split_meta = {}

    def smeta(split, qid):
        if split not in split_meta:
            p = ROOT / split / 'meta.jsonl'
            split_meta[split] = {m['id']: m for m in read_jsonl(p)} if p.exists() else {}
        return split_meta[split].get(qid) or {}

    recs, dropped = {}, collections.Counter()
    for m in metas:
        pool = pool_of(m['split'])
        run = os.path.basename(m.get('run_path') or m.get('run') or '')
        if pool == 'forbidden':
            raise SystemExit(f"test split in the package: {m['split']}")
        if pool == 'never' or SKIP_RUN.match(run):
            dropped[f"not_used:{m['split'] if pool == 'never' else run}"] += 1
            continue
        if (m.get('industry') in VAL_INDUSTRIES) or (m.get('family') in VAL_FAMILIES):
            raise SystemExit(f"held-out industry/family on the train side: {m['key']} (package built without --val-*)")
        k = (m['run_path'], m['split'], m['id'], m.get('sample', 0))
        r = recs.setdefault(k, Rec(k))
        r.metas.append(m)
        r.samples.append(m['key'])
        r.pool = pool
    # strata + priority inside strata
    for r in recs.values():
        m, sm = r.m, smeta(r.m['split'], r.m['id'])
        r.group = m['group']
        r.intent = (m.get('intent') or sm.get('intent') or 'unknown').replace('train:', '')
        r.flags_ = r.flags()
        r.changed = bool(sm.get('changed') or sm.get('moved'))
        r.variant = m['split'].rsplit('/', 1)[-1]
        r.rnd = hfrac(a.seed, m['split'], m['id'])
    if a.gate:
        gt = json.loads(Path(a.gate).read_text(encoding='utf-8'))
        drop, ok_runs = {tuple(x) for x in gt['drop_intents']}, {os.path.normpath(x) for x in gt['train_runs']}
        for k in list(recs):
            r = recs[k]
            if r.pool in ('rule', 'syn') and os.path.normpath(r.m['run_path']) not in ok_runs:
                dropped[f'gate_run:{r.m["run_path"]}'] += len(r.samples)
                del recs[k]
            elif (r.m['split'], r.intent) in drop:
                dropped[f'gate_intent:{r.variant}:{r.intent}'] += len(r.samples)
                del recs[k]
    sh = shares(a.budget)
    total = sum(len(r.samples) for r in recs.values())
    avail = {p: sum(len(r.samples) for r in recs.values() if r.pool == p) for p in sh}
    quota = {p: a.budget * sh[p] for p in sh}
    # a pool short of samples gives its quota to the others (std first, then syn)
    short = sum(max(0.0, quota[p] - avail[p]) for p in sh)
    for p in sh:
        quota[p] = min(quota[p], avail[p])
    for p in SPILL:
        add = min(short, avail[p] - quota[p])
        quota[p] += add
        short -= add
    chosen = {}

    # --- std: one skin per question group (rotated by hash), rare behaviours get a second skin -------------------
    std = [r for r in recs.values() if r.pool == 'std']
    by_group = collections.defaultdict(list)
    for r in std:
        by_group[r.group].append(r)
    primary, secondary = [], []
    for g, rs in by_group.items():
        rs.sort(key=lambda r: hfrac(a.seed, 'skin', g, r.m['split']))
        primary.append(rs[0])
        secondary += rs[1:2]                     # at most 2 records of one question in the mix
    # second skin only for repair behaviours (multi-turn); unanswerable / no_program stay at their natural rate
    # (graded by type only: doubling them would push the student towards answering 'unanswerable')
    rare_second = [r for r in secondary if (by_group[r.group][0].flags_ | r.flags_) & REPAIR]
    q = quota['std']
    # rare behaviours first (both skins), then the rest stratified by intent
    rare_first = sorted([r for r in primary if r.flags_], key=lambda r: r.rnd) + sorted(rare_second, key=lambda r: r.rnd)
    used = 0
    rare_cap = a.rare_max * q
    for r in rare_first:
        if used + len(r.samples) > rare_cap:
            break
        chosen[r.key] = 'std:rare'
        used += len(r.samples)
    strata = collections.defaultdict(list)
    for r in sorted(primary, key=lambda r: r.rnd):
        strata[r.intent].append(r)
    used += take(strata, q - used, ALPHA['std'], chosen, a.seed, 'std')
    if q - used > 50:                            # budget left: second skins, stratified
        strata = collections.defaultdict(list)
        for r in sorted(secondary, key=lambda r: r.rnd):
            strata[r.intent].append(r)
        used += take(strata, q - used, ALPHA['std'], chosen, a.seed, 'std:skin2')

    # --- rule: changed answers first, paraphrase capped, strata = (variant, intent) --------------------------------
    rule = [r for r in recs.values() if r.pool == 'rule']
    q = quota['rule']
    # a train question asked again under a rulebook that does not move its answer (paraphrase, unchanged) is a near
    # copy of its std records: at most MAX_PER_GROUP records of one train question across std + rule
    per_group = collections.Counter(recs[k].group for k in chosen)
    near_copy = [r for r in rule if not r.changed and r.group.startswith('q_') and r.group in by_group]
    room = {g: max(0, MAX_PER_GROUP - per_group[g]) for g in {r.group for r in near_copy}}
    keep_copy = set()
    for r in sorted(near_copy, key=lambda r: r.rnd):
        if room[r.group] > 0:
            room[r.group] -= 1
            keep_copy.add(r.key)
    near_keys = {r.key for r in near_copy}
    rule = [r for r in rule if r.changed or r.key not in near_keys or r.key in keep_copy]
    para = [r for r in rule if r.variant == 'rulevar_paraphrase']
    rest = [r for r in rule if r.variant != 'rulevar_paraphrase']
    used = 0
    strata = collections.defaultdict(list)
    for r in sorted(para, key=lambda r: r.rnd):
        strata[('para', r.intent)].append(r)
    used += take(strata, min(q * PARAPHRASE_MAX, sum(len(r.samples) for r in para)), ALPHA['rule'], chosen, a.seed, 'rule:para')
    # unchanged answers under a changed rulebook (contrast: read the change, see it does not apply): a fixed share
    strata = collections.defaultdict(list)
    for r in sorted([r for r in rest if not r.changed], key=lambda r: (not (r.flags_ & REPAIR), r.rnd)):
        strata[(r.variant, r.intent)].append(r)
    used += take(strata, q * UNCHANGED_SHARE, ALPHA['rule'], chosen, a.seed, 'rule:unchanged')
    strata = collections.defaultdict(list)
    for r in sorted([r for r in rest if r.changed], key=lambda r: (not (r.flags_ & REPAIR), r.rnd)):
        strata[(r.variant, r.intent)].append(r)
    used += take(strata, q - used, ALPHA['rule'], chosen, a.seed, 'rule')

    # --- syn: strata = (split, intent), repair behaviours first (moved answers are not favoured) -------------------
    syn = [r for r in recs.values() if r.pool == 'syn']
    strata = collections.defaultdict(list)
    for r in sorted(syn, key=lambda r: (not (r.flags_ & REPAIR), r.rnd)):
        strata[(r.variant, r.intent)].append(r)
    take(strata, quota['syn'], ALPHA['syn'], chosen, a.seed, 'syn')

    # --- budget left (a pool ran out, e.g. std capped at 2 skins per question): syn, rule, then 3rd skins ---------
    for pool in SPILL:                           # rule: only changed answers (the paraphrase/unchanged caps hold)
        left = a.budget - sum(len(recs[k].samples) for k in chosen)
        if left <= 50:
            break
        tag = pool + ':fill'
        pool_recs = rule if pool == 'rule' else [r for r in recs.values() if r.pool == pool]
        if pool == 'std':                        # a 3rd std record only while the question stays under MAX_PER_GROUP
            per_group = collections.Counter(recs[k].group for k in chosen)
            pool_recs = [r for r in pool_recs if per_group[r.group] < MAX_PER_GROUP]
        strata = collections.defaultdict(list)
        for r in sorted([r for r in pool_recs if pool != 'rule' or r.changed], key=lambda r: r.rnd):
            strata[(r.variant, r.intent)].append(r)
        take(strata, left, ALPHA[pool], chosen, a.seed, tag)

    # --- leak checks -------------------------------------------------------------------------------------------------
    sel = [r for r in recs.values() if r.key in chosen]
    val_groups = {m['group'] for m in vmetas} | {x['group'] for x in vq}
    val_shops = {m['shop'] for m in vmetas}
    errors = []
    for r in sel:
        m = r.m
        if r.group in val_groups:
            errors.append(f'group in val: {m["key"]}')
        if m['shop'] in val_shops or any(m['shop'].endswith('/' + s) for s in VAL_SHOPS):
            errors.append(f'held-out shop: {m["key"]}')
        if pool_of(m['split']) not in ('std', 'rule', 'syn'):
            errors.append(f'pool: {m["key"]}')
    if errors:
        raise SystemExit('leak check failed:\n' + '\n'.join(errors[:20]))
    keys = {k for r in sel for k in r.samples}

    # --- write -------------------------------------------------------------------------------------------------------
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(pkg / 'train.jsonl', encoding='utf-8') as fi, open(out / 'train.jsonl.tmp', 'w', encoding='utf-8') as fo:
        for line in fi:
            i = line.find('"id": "')
            sid = json.loads(line)['id'] if i < 0 else line[i + 7:line.index('"', i + 7)]
            if sid in keys:
                fo.write(line)
                n += 1
    os.replace(out / 'train.jsonl.tmp', out / 'train.jsonl')
    if n != len(keys):
        raise SystemExit(f'wrote {n} samples, selected {len(keys)}: train.jsonl and train_meta.jsonl disagree')
    with open(out / 'train_meta.jsonl', 'w', encoding='utf-8') as f:
        for m in metas:
            if m['key'] in keys:
                rk = (m['run_path'], m['split'], m['id'], m.get('sample', 0))
                f.write(json.dumps({**m, 'mix': chosen[rk]}, ensure_ascii=False) + '\n')
    for name in ('val.jsonl', 'val_meta.jsonl', 'val_questions.jsonl', 'sft_lora.py', 'README.md'):
        if (pkg / name).exists():
            shutil.copyfile(pkg / name, out / name)
    if (pkg / 'stats.json').exists():
        shutil.copyfile(pkg / 'stats.json', out / 'package_stats.json')

    def dist(f):
        return dict(collections.Counter(f(r) for r in sel for _ in r.samples).most_common())
    groups = collections.Counter(r.group for r in sel if r.pool == 'std')
    eval_sets = collections.Counter(x['split'] for x in vq)
    stats = {'created_at': dt.datetime.now().isoformat(timespec='seconds'), 'argv': sys.argv, 'package': str(pkg),
             'package_sha256': {f: sha256(pkg / f) for f in ('train.jsonl', 'train_meta.jsonl') if (pkg / f).exists()},
             'budget': a.budget, 'seed': a.seed, 'shares': {p: round(v, 3) for p, v in sh.items()},
             'available_samples': {'total': total, **avail}, 'quota': {p: round(v) for p, v in quota.items()},
             'selected_samples': len(keys), 'selected_records': len(sel), 'dropped_from_package': dict(dropped),
             'by_pool': dist(lambda r: r.pool), 'by_tag': dist(lambda r: chosen[r.key]),
             'by_split': dist(lambda r: r.m['split']),
             'final_vs_explore': dict(collections.Counter('final' if m.get('final') else 'explore'
                                                          for r in sel for m in r.metas)),
             'rare_flags': dict(collections.Counter(f for r in sel for f in r.flags_)),
             'changed_or_moved': dist(lambda r: f'{r.pool}:{r.changed}'),
             'std_groups': len(groups), 'std_groups_with_2_skins': sum(1 for v in groups.values() if v > 1),
             'intents_top': collections.Counter(f'{r.pool}:{r.intent}' for r in sel for _ in r.samples).most_common(25),
             'intents_count': {p: len({r.intent for r in sel if r.pool == p}) for p in sh},
             'industries': dist(lambda r: str(r.m.get('industry'))),
             'gold_type': dist(lambda r: r.m.get('gold_type')),
             'mean_total_tokens': round(sum(m.get('total_tokens') or 0 for r in sel for m in r.metas) / max(1, len(keys)), 1),
             'sum_total_tokens': sum(m.get('total_tokens') or 0 for r in sel for m in r.metas),
             'val': {'samples': len(vmetas), 'questions_by_split': dict(eval_sets)},
             'leak_checks': 'ok: no selected group in val_meta/val_questions, no held-out shop/industry/family, no test split'}
    (out / 'mix_stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: stats[k] for k in ('budget', 'shares', 'available_samples', 'quota', 'selected_samples',
                                            'by_pool', 'by_tag', 'rare_flags', 'std_groups', 'std_groups_with_2_skins',
                                            'intents_count', 'mean_total_tokens', 'val')}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--out', default=str(ROOT / 'outputs' / 'sft_plan'))
    c = sub.add_parser('check', help='(run_teacher.sh) split unchanged since the plan, stage budget left')
    c.add_argument('--plan', required=True)
    c.add_argument('--split', required=True)
    c.add_argument('--run', required=True)
    g = sub.add_parser('gate', help='(package_and_select.sh) runs complete, accuracy per split/intent -> gate.json')
    g.add_argument('--plan', required=True)
    g.add_argument('--min-rate', type=float, default=0.7)
    g.add_argument('--min-n', type=int, default=8)
    g.add_argument('--allow-incomplete', action='store_true', help='package although some planned records are missing')
    g.add_argument('--allow-drop', action='store_true', help='accept leaving a whole split < min-rate out of the package')
    g.add_argument('--max-abstain', type=float, default=0.03)
    s = sub.add_parser('select')
    s.add_argument('--gate', help='gate.json: (split, intent) pairs to drop')
    s.add_argument('--package', required=True, help='full package (gen.package --per-group 3 of every usable run)')
    s.add_argument('--budget', type=int, required=True, help='training samples (one sample = one model turn)')
    s.add_argument('--out', required=True)
    s.add_argument('--seed', type=int, default=0)
    s.add_argument('--rare-max', type=float, default=0.15, help='at most this share of the std quota for rare-behaviour records')
    a = ap.parse_args()
    {'plan': plan, 'check': check, 'gate': gate, 'select': select}[a.cmd](a)


if __name__ == '__main__':
    main()
