"""Rulebook-variant splits on the five calibrated train shops (S4 on train shops; no model calls). Each split pairs
one changed rule (gen.variants) with the shops whose oracle matches the gold on every train question
(biz_123/111/127/129/106): rulebook.md = the variant text, gold = the oracle under the variant rules. The point is to
teach reading `rulebook_changes`, so most questions are ones whose answer the change moves, and a minority are not
moved (a changed rule does not always change the answer). A `paraphrase` split rewords some standard lines without
changing their meaning: the agent lists them as changes, the answers stay the standard ones.

    python -m gen.rule_variants --out data_gen [--variants all] [--per-variant 220] [--reskin data_gen/reskin_1,data_gen/reskin_2]
    (memory: ~2.2 GB peak per variant, measured; run one variant per process, the summary merges across calls)
    -> data_gen/rulevar_<variant>/  rulebook.md, calendar.csv, data/<shop> (link to a reskinned copy when given, so
       the five shops do not look the same in every variant; else to data/train), questions.jsonl, answers.jsonl,
       meta.jsonl (orig_id, intent, variant, changed, source train|generated, reskin)
    -> data_gen/rulevar_summary.json  sizes, changed/unchanged, pipeline checks (rulebook_changes, system prompt)

Questions: the shops' train questions (parsed by gen.parse; the default-rule oracle must equal the train gold), and
generated ones (gen.questions with the variant's intents weighted up, written by gen.surface; kept only when the
written text parses back to an equal answer). Teacher runs on these splits need the user's approval (see the
`teacher` block of the summary for the dry-run estimate).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import gc
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT), str(ROOT / 'scripts')]

from datamate.eval import correct  # noqa: E402
from gen import surface as S  # noqa: E402
from gen import variants as V  # noqa: E402
from gen.oracle import Rules, View, answer, undetermined  # noqa: E402
from gen.parse import Names, parse  # noqa: E402
from gen.remap import NameMap  # noqa: E402

TRAIN = ROOT / 'data' / 'train'
CALIBRATED = ['biz_123', 'biz_111', 'biz_127', 'biz_129', 'biz_106']
PARAPHRASE = 'paraphrase'
VIEW_CACHE = 4             # oracle Views kept per shop (each is large; peak RSS was 22 GB with no bound)


# Questions the variant's rulebook does not fix (gen.oracle.undetermined: intents sharing the valid-order set of §1
# under returns_count / delivering_out, line-part revenue under revenue_voucher) are left out, changed or not.


def _vseed(variant):
    """A number of the variant's name: ids and copies do not depend on which variants one call builds."""
    return int(hashlib.sha1(variant.encode()).hexdigest()[:4], 16) % 1000


def _jsonl(path):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def _write_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=_plain) + '\n')


def _plain(x):
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    if isinstance(x, (dt.date, dt.datetime)):
        return x.isoformat()
    if isinstance(x, (set, tuple)):
        return list(x)
    return str(x)


def _clean(v):
    return json.loads(json.dumps(v, default=_plain))


def same(a, b, alias=None):
    """Two oracle answers equal under the competition's comparison."""
    ta, va = a
    tb, vb = b
    return correct({'type': ta, 'answer': _clean(va)}, {'type': tb, 'answer': _clean(vb), 'alias': alias})


class Shop:
    """Ledger, names, views and text values of one calibrated shop."""

    def __init__(self, b):
        from calibrate_oracle import load
        self.b, self.L = b, load(b)
        self.names, self.views = Names(self.L), {}
        self._values = None

    def answer(self, spec, as_of, rules):
        key = (as_of, rules)
        if key not in self.views:
            if len(self.views) >= VIEW_CACHE:         # a View holds whole-ledger frames: keep only a few (memory)
                self.views.pop(next(iter(self.views)))
            self.views[key] = View(self.L, as_of, rules)
        try:
            return answer(self.L, spec, as_of, rules, view=self.views[key])
        except Exception as exc:                            # noqa: BLE001 - an intent the oracle cannot run here
            return 'error', repr(exc)[:80]

    def alias(self, kind, ans):
        from gen.build import _codes, _text_values, answer_alias
        if self._values is None:
            from datamate.data import load_business
            business = load_business(TRAIN / 'data' / self.b, TRAIN / 'calendar.csv', ROOT / 'outputs' / 'cache')
            self._values = (_text_values(business), _codes(self.L))
        values, codes = self._values
        return answer_alias(kind, ans, codes, values, self.L.shop.get('caps', set()))


def train_candidates(shop: Shop, questions, gold, rules):
    """(question, gold under the variant, changed) for the shop's train questions the oracle reproduces."""
    out = []
    for q in sorted(questions, key=lambda q: q['as_of_date']):      # one as_of at a time: views reused
        as_of = dt.date.fromisoformat(q['as_of_date'])
        try:
            spec = parse(q['question'], as_of, shop.L, shop.names)
        except Exception:                                   # noqa: BLE001
            spec = None
        if spec is None:
            continue
        if spec.get('period') is None and 'period' in spec:
            spec = {**spec, 'period': {'kind': 'today'}}
        g = gold[q['id']]
        base = shop.answer(spec, as_of, Rules())
        if base[0] == 'error' or not correct({'type': base[0], 'answer': _clean(base[1])}, g):
            continue
        var = shop.answer(spec, as_of, rules)
        if var[0] == 'error':
            continue
        changed = not same(var, base, g.get('alias'))
        new = dict(g) if not changed else {'id': q['id'], 'type': var[0], 'answer': _clean(var[1]),
                                           'alias': shop.alias(var[0], var[1])}
        out.append({'q': q, 'gold': new, 'changed': changed, 'intent': spec['intent'], 'source': 'train',
                    'undetermined': undetermined(spec, rules, shop.L)})
    return out


def generated_candidates(shop: Shop, variant, rules, n, seed):
    """Oracle questions sampled with the variant's intents weighted up, written as text and parsed back."""
    from gen.build import variant_questions
    rng = np.random.default_rng(seed)
    prng = random.Random(seed)
    out = []
    try:
        qs = variant_questions(shop.L, rng, n, variant, rules, keep_unaffected=0.5) if variant in V.VARIANTS else []
    except Exception:                                       # noqa: BLE001
        qs = []
    for k, q in enumerate(qs):
        as_of = q['as_of']
        try:
            text = S.noisify(S.realize(q['spec'], S.make_ctx(shop.L, q['spec'], as_of), prng), prng)
            spec2 = parse(text, as_of, shop.L, shop.names)
        except Exception:                                   # noqa: BLE001
            continue
        if spec2 is None:
            continue
        var = shop.answer(spec2, as_of, rules)
        if var[0] in ('error',) or not same(var, (q['type'], q['answer'])):
            continue
        base = shop.answer(spec2, as_of, Rules())
        changed = base[0] == 'error' or not same(var, base)
        qid = f'q_rv{seed:06d}_{shop.b[4:]}_{k:04d}'
        out.append({'q': {'id': qid, 'business_id': shop.b, 'question': text, 'as_of_date': as_of.isoformat()},
                    'gold': {'id': qid, 'type': var[0], 'answer': _clean(var[1]), 'alias': shop.alias(var[0], var[1])},
                    'changed': changed, 'intent': spec2['intent'], 'source': 'generated',
                    'undetermined': undetermined(spec2, rules, shop.L)})
    return out


def select(cands, per_variant, changed_share, rng: random.Random):
    """Changed questions first (train text before generated, shops in turn), then unchanged ones up to the share."""
    want_changed = int(round(per_variant * changed_share))
    def take(pool, n):
        by_shop = collections.defaultdict(list)
        for c in pool:
            by_shop[c['q']['business_id']].append(c)
        for v in by_shop.values():
            rng.shuffle(v)
            v.sort(key=lambda c: c['source'] != 'train')
        out = []
        while len(out) < n and any(by_shop.values()):
            for b in sorted(by_shop):
                if by_shop[b] and len(out) < n:
                    out.append(by_shop[b].pop(0))
        return out
    changed = take([c for c in cands if c['changed']], want_changed)
    n_unchanged = max(int(round(len(changed) * (1 - changed_share) / changed_share)), 1) if changed else 0
    unchanged = take([c for c in cands if not c['changed']], n_unchanged)
    return changed + unchanged


def link_shop(split: Path, b: str, reskins):
    """data/<b> -> a reskinned copy of the shop (the copy's name map maps label answers) or the train shop."""
    target, nm, which = (TRAIN / 'data' / b).resolve(), NameMap({}, {}), None
    for r in reskins:
        plan = json.loads((r / 'reskin.json').read_text(encoding='utf-8'))['shops'].get(b)
        if plan and plan['ok'] and (r / 'data' / b).is_dir():
            target, nm, which = (r / 'data' / b).resolve(), NameMap(plan['names'], plan['label_map'], plan.get('keep', ())), r.name
            break
    os.symlink(os.path.relpath(target, split / 'data'), split / 'data' / b)
    return nm, which


def pipeline_check(split: Path, variant_text: str, fragments):
    """What the agent sees for this split: the rulebook lines it lists as changed, and its system prompt."""
    from datamate.prompt import system_prompt
    from datamate.runner import load_rulebook
    doc, stats, changed, system = load_rulebook(split / 'rulebook.md')
    train_system = system_prompt()
    found = [f for f in fragments if any(f in c for c in changed)]
    return {'changed_lines': len(changed), 'gone': stats['gone'], 'full': stats['full'],
            'fragments_in_changes': f'{len(found)}/{len(fragments)}', 'system_differs_from_train': system != train_system,
            'system_chars': len(system), 'train_system_chars': len(train_system),
            'document': 'changes_only' if changed else 'standard', 'rulebook_changes': changed}


def catalog_check(split: Path, b: str):
    """rulebook_changes in the catalog the agent builds for one shop of the split."""
    from datamate.runner import Businesses, load_rulebook
    rulebook, _, changed, _ = load_rulebook(split / 'rulebook.md')
    business, catalog, _ = Businesses(split, rulebook, ROOT / 'outputs' / 'cache', changed).get(b)
    return {'shop': b, 'catalog_rulebook_changes': len(catalog.get('rulebook_changes') or []),
            'unreadable_files': len(business.unreadable)}


def dry_run(split: Path, workers=16):
    """gen.teacher --dry-run estimate for one split (no model call)."""
    cmd = [sys.executable, '-m', 'gen.teacher', '--split', str(split), '--out', str(ROOT / 'outputs' / 'teacher' / ('dry_' + split.name)),
           '--all', '--dry-run', '--workers', str(workers), '--concurrency', str(workers)]
    env = {**os.environ, 'PYTHONPATH': f"{ROOT / 'src'}:{ROOT}", 'PYTHONIOENCODING': 'utf-8'}
    try:
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300, env=env)
        line = next((l for l in res.stdout.splitlines() if l.startswith('{')), None)
        return json.loads(line) if line else {'error': (res.stderr or res.stdout)[-300:]}
    finally:
        shutil.rmtree(ROOT / 'outputs' / 'teacher' / ('dry_' + split.name), ignore_errors=True)


def build(out: Path, variants, per_variant=220, changed_share=.75, generated=40, reskins=(), seed=0, quiet=False, passes=4):
    log = (lambda *a: None) if quiet else (lambda *a: print(*a, file=sys.stderr, flush=True))
    questions = _jsonl(TRAIN / 'questions.jsonl')
    gold = {g['id']: g for g in _jsonl(TRAIN / 'answers.jsonl')}
    shops = {b: Shop(b) for b in CALIBRATED}
    by_shop = {b: [q for q in questions if q['business_id'] == b] for b in CALIBRATED}
    summary = {'per_variant': per_variant, 'changed_share': changed_share, 'seed': seed, 'reskins': [r.name for r in reskins],
               'splits': {}}
    for vi, variant in enumerate(variants):
        rng = random.Random(f'{seed}:{variant}')
        split = out / f'rulevar_{variant}'
        if split.exists():
            shutil.rmtree(split)
        (split / 'data').mkdir(parents=True)
        shutil.copy(TRAIN / 'calendar.csv', split / 'calendar.csv')
        if variant == PARAPHRASE:
            text, rules, fragments = V.paraphrase_words(), Rules(), [new for _, new in V.REWORDINGS]
        else:
            text, rules, fragments = V.rulebook_text(variant), V.rules_of(variant), [new for _, new in V.VARIANTS[variant][1]]
        (split / 'rulebook.md').write_text(text, encoding='utf-8')
        cands = []
        for b in CALIBRATED:
            cands += train_candidates(shops[b], by_shop[b], gold, rules)
        want = int(round(per_variant * changed_share))
        for rnd in range(passes if generated and variant != PARAPHRASE else 0):   # more passes while changed ones are few
            if rnd and sum(c['changed'] for c in cands) >= want:
                break
            for si, b in enumerate(CALIBRATED):
                cands += generated_candidates(shops[b], variant, rules, generated, seed * 100000 + _vseed(variant) * 1000 + rnd * 10 + si)
        n_excluded = sum(bool(c.get('undetermined')) for c in cands)
        cands = [c for c in cands if not c.get('undetermined')]
        share = 0.0 if variant == PARAPHRASE else changed_share
        if variant == PARAPHRASE:
            chosen = select([{**c, 'changed': True} for c in cands], per_variant, 1.0, rng)
            for c in chosen:
                c['changed'] = False
        else:
            chosen = select(cands, per_variant, share, rng)
        maps = {}
        r0 = _vseed(variant) % len(reskins) if reskins else 0         # copy chosen by variant name
        order = list(reskins[r0:]) + list(reskins[:r0])
        for b in CALIBRATED:
            maps[b] = link_shop(split, b, order)
        qs, ans, meta, dropped = [], [], [], collections.Counter()
        for c in sorted(chosen, key=lambda c: c['q']['id']):
            nm, which = maps[c['q']['business_id']]
            g = nm.map_answer(c['gold']) if nm else c['gold']
            if g is None or (nm and nm.stale(prose=c['q']['question'])):
                dropped['renamed_name_in_question_or_answer'] += 1
                continue
            qs.append(c['q'])
            ans.append(g)
            meta.append({'id': c['q']['id'], 'orig_id': c['q']['id'] if c['source'] == 'train' else None,
                         'business_id': c['q']['business_id'], 'intent': c['intent'], 'variant': variant,
                         'changed': c['changed'], 'source': c['source'], 'reskin': which})
        _write_jsonl(split / 'questions.jsonl', qs)
        _write_jsonl(split / 'answers.jsonl', ans)
        _write_jsonl(split / 'meta.jsonl', meta)
        info = {'questions': len(qs), 'changed': sum(m['changed'] for m in meta), 'unchanged': sum(not m['changed'] for m in meta),
                'candidates': {'train': sum(c['source'] == 'train' for c in cands),
                               'train_changed': sum(c['source'] == 'train' and c['changed'] for c in cands),
                               'generated': sum(c['source'] == 'generated' for c in cands),
                               'generated_changed': sum(c['source'] == 'generated' and c['changed'] for c in cands)},
                'by_source': dict(collections.Counter(m['source'] for m in meta)),
                'by_shop': dict(collections.Counter(m['business_id'] for m in meta)),
                'by_intent': dict(collections.Counter(m['intent'] for m in meta).most_common()),
                'dropped': dict(dropped, undetermined=n_excluded), 'pipeline': pipeline_check(split, text, fragments)}
        summary['splits'][split.name] = info
        for sh in shops.values():                      # nothing kept across variants but the ledgers
            sh.views.clear()
        cands = chosen = None
        gc.collect()
        log(f"{split.name}: {info['questions']} questions ({info['changed']} changed), candidates {info['candidates']}, "
            f"pipeline: {info['pipeline']['changed_lines']} changed lines, fragments {info['pipeline']['fragments_in_changes']}")
    return summary


def _total(splits):
    total = {'questions': 0, 'est_calls': 0, 'est_minutes_at_16': 0.0, 'est_usd': 0.0}
    for info in splits.values():
        d = info.get('teacher_dry_run') or {}
        for k_out, k_in in (('questions', 'questions'), ('est_calls', 'est_calls'), ('est_minutes_at_16', 'est_minutes'), ('est_usd', 'est_usd')):
            total[k_out] += d.get(k_in) or 0
    return {k: round(v, 2) for k, v in total.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default=str(ROOT / 'data_gen'))
    ap.add_argument('--variants', default='all', help=f'comma separated names of gen.variants.VARIANTS and/or {PARAPHRASE}')
    ap.add_argument('--per-variant', type=int, default=220)
    ap.add_argument('--changed-share', type=float, default=.75)
    ap.add_argument('--generated', type=int, default=40, help='generated questions tried per shop and variant')
    ap.add_argument('--reskin', default='', help='reskinned splits (gen.reskin) whose shop copies the splits link to')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--no-checks', action='store_true', help='skip the catalog check and the teacher dry run')
    a = ap.parse_args(argv)
    names = list(V.VARIANTS) + [PARAPHRASE] if a.variants == 'all' else [v for v in a.variants.split(',') if v]
    reskins = [Path(r) for r in a.reskin.split(',') if r]
    out = Path(a.out)
    summary = build(out, names, a.per_variant, a.changed_share, a.generated, reskins, a.seed)
    if not a.no_checks:
        for name, info in summary['splits'].items():
            info['catalog'] = catalog_check(out / name, CALIBRATED[0])
            info['teacher_dry_run'] = dry_run(out / name)
        summary['teacher_total'] = _total(summary['splits'])
    path = out / 'rulevar_summary.json'                # splits built by earlier calls (one variant per process) stay
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        summary['splits'] = {**{k: v for k, v in old.get('splits', {}).items() if (out / k).is_dir()}, **summary['splits']}
        if 'teacher_total' in summary or 'teacher_total' in old:
            summary['teacher_total'] = _total(summary['splits'])
    (out / 'rulevar_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=_plain), encoding='utf-8')
    print(json.dumps({k: {x: y for x, y in v.items() if x in ('questions', 'changed', 'unchanged', 'by_source')}
                      for k, v in summary['splits'].items()}, ensure_ascii=False))
    if 'teacher_total' in summary:
        print(json.dumps(summary['teacher_total']))


if __name__ == '__main__':
    main()
