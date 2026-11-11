"""Hand-off SFT package from teacher runs (gen.teacher): one folder another person can train from right away.

    python -m gen.package --teacher outputs/teacher/train_v1 [more runs...] --out outputs/sft/train_v1

Writes <out>/:
  train.jsonl, val.jsonl            one sample per line: {"id", "prompt": [messages], "completion": [assistant]}
  train_meta.jsonl, val_meta.jsonl  the same lines' meta (question, group, shop, turn, types, flags, token counts)
  val_questions.jsonl               every question of the held-out shops/groups (also those the teacher failed):
                                    run the agent on them for an unbiased accuracy of the trained model
  stats.json                        sources, filters and what each dropped, distributions, lengths, file hashes
  README.md                         what the data is, how to train, serve and evaluate (Vietnamese)
  sft_lora.py                       the training script (copy of train/sft_lora.py)

Pipeline (each step counted in stats.json):
  1. records of every run (test splits refused); a question answered by several records keeps the `--per-question`
     best (fewest calls, fewest failed turns); `--per-group` caps records per question group and rulebook (a train
     question and its rewrites/reskinned copies: runs listed first win; a rulebook variant counts apart);
     `--cap-intent` caps records per intent;
  2. samples of a correct record (gen.sft.teacher_samples): its final turn and clean explore turns;
  3. prompts: `current` (default) rebuilds each prompt with the current agent code (prompt.messages over the catalog,
     the data lookup and the recorded history) so the student sees exactly what inference sends; a prompt that
     differs from the recorded one is flagged `prompt_drift` (`--drop-drift` drops it); `recorded` keeps the
     messages as sent (no data loading);
  4. filters: `--no-explore`, `--drop-weak`, too long (`--max-len`, Gemma tokens of prompt + completion, never
     truncated), exact duplicates;
  5. split: held-out shops (`--val-shops`, default three train shops of different export families), industries or
     families (synthetic splits), then `--val-frac` of the remaining question groups; a group (a question and all
     its rewrites) and a shop are never on both sides;
  6. write, then gen.validate checks the package.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from datamate import prompt  # noqa: E402
from datamate.catalog import lookup  # noqa: E402
from datamate.runner import Businesses, load_rulebook, read_jsonl  # noqa: E402
from gen.sft import SFT_SCHEMA, group_of, history_of, teacher_samples, teacher_turns  # noqa: E402
from gen.tokens import TokenCounter  # noqa: E402

PACKAGE_SCHEMA = 'datamate_sft_package/v1'
FORBIDDEN = ('public_test', 'private_test')
# Held out by default: KiotViet lists (biz_108, family E), MISA ledger (biz_130, F), a one-file invoice CSV (biz_110);
# none is one of the five shops whose ledger gen.augment_train rewrites. 277 of the 3000 train questions (9%).
DEFAULT_VAL_SHOPS = ('biz_108', 'biz_110', 'biz_130')
DEFAULT_MAX_LEN = 24576      # turn-0 prompts of all 3000 train questions: max 18.9k Gemma tokens; later turns add history
README_TEMPLATE = ROOT / 'gen' / 'assets' / 'sft_package_readme.md'
TRAIN_SCRIPT = ROOT / 'train' / 'sft_lora.py'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def forbidden(path) -> bool:
    return any(f in str(path) for f in FORBIDDEN)


def resolve(path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def rel(path) -> str:
    """A path as stored in the package: relative to the repo when inside it."""
    p = Path(os.path.abspath(path))
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def shop_key(split: Path, business_id) -> str:
    """The shop's folder (symlinks resolved, relative to the repo): a rewritten split that links train's data/
    (gen.augment_train) shares its shops; synthetic splits that reuse an id do not."""
    return rel(os.path.realpath(split / 'data' / str(business_id)))


def matches_shop(key: str, entries) -> bool:
    return any(key == e or key.endswith('/' + e) for e in entries)


def percentiles(xs):
    xs = sorted(xs)
    if not xs:
        return {}
    pick = lambda q: xs[min(len(xs) - 1, int(q * len(xs)))]
    return {'n': len(xs), 'min': xs[0], 'p50': pick(.5), 'p90': pick(.9), 'p99': pick(.99), 'max': xs[-1],
            'mean': round(sum(xs) / len(xs), 1)}


def git_info():
    def git(*a):
        try:
            return subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:                                   # noqa: BLE001
            return None
    return {'commit': git('rev-parse', 'HEAD'),
            'dirty_files': [l.split(maxsplit=1)[-1] for l in (git('status', '--porcelain') or '').splitlines()]}


_INTENTS = None


def train_intent(group):
    """Coarse intent of a train question (scripts/train_intents.py keyword rules), for caps and stats only."""
    global _INTENTS
    if _INTENTS is None:
        try:
            spec = importlib.util.spec_from_file_location('train_intents', ROOT / 'scripts' / 'train_intents.py')
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _INTENTS = {q['id']: 'train:' + mod.intent(q['question'], mod.A[q['id']]) for q in mod.Q}
        except Exception:                                   # noqa: BLE001 - no train data here: no intents
            _INTENTS = {}
    return _INTENTS.get(group)


class Split:
    """One source split: its questions, gold, generator meta, and (for `current` prompts) the agent's own view."""

    def __init__(self, path: Path, cache_dir: Path):
        self.path = path
        self.questions = {q['id']: q for q in read_jsonl(path / 'questions.jsonl')} if (path / 'questions.jsonl').exists() else {}
        self.meta = {m['id']: m for m in read_jsonl(path / 'meta.jsonl')} if (path / 'meta.jsonl').exists() else {}
        self.cache_dir, self._agent, self._lookups = cache_dir, None, {}

    def agent(self):
        if self._agent is None:
            rulebook, _, changed, system = load_rulebook(self.path / 'rulebook.md')
            self._agent = (Businesses(self.path, rulebook, self.cache_dir, changed), system)
        return self._agent

    def rebuild(self, rec, turns, t):
        """The messages the current agent code sends at turn t of this record (solve's own construction)."""
        businesses, system = self.agent()
        business, catalog, _ = businesses.get(rec['business_id'])
        key = (rec['business_id'], rec['question'])
        if key not in self._lookups:
            self._lookups[key] = lookup(rec['question'], business)
        max_calls = (rec.get('input') or {}).get('max_calls') or 3
        return prompt.messages(catalog, rec['question'], rec['as_of'], self._lookups[key], history_of(turns, t),
                               max_calls - t, t == max_calls - 1, system)

    def rulebook_sha(self):
        p = self.path / 'rulebook.md'
        return hashlib.sha1(p.read_bytes()).hexdigest()[:12] if p.is_file() else ''

    def group(self, qid):
        """Question group: an `orig_id` given by the generator (meta.jsonl or questions.jsonl), else gen.sft.group_of."""
        orig = (self.meta.get(qid) or {}).get('orig_id') or (self.questions.get(qid) or {}).get('orig_id')
        return group_of(qid, orig)

    def info(self, qid, group):
        m = self.meta.get(qid) or self.meta.get(group) or {}
        return {'intent': m.get('intent') or train_intent(group), 'industry': m.get('industry'), 'family': m.get('family')}


def load_records(run: Path):
    """(file name, record) for each teacher record of a run."""
    for path in sorted((run / 'logs').glob('*.json')):
        try:
            rec = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            yield path.name, None
            continue
        if not str(rec.get('schema', '')).startswith('teacher_record'):
            yield path.name, None
            continue
        rec['_file'] = path.name
        yield path.name, rec


def run_split(run: Path, rec) -> Path:
    """The record's split folder: as given to gen.teacher (relative to the repo), else the run's resolved path."""
    given = (rec.get('input') or {}).get('split')
    if given and (resolve(given) / 'questions.jsonl').exists():
        return resolve(given)
    try:
        runs = json.loads((run / 'run.json').read_text(encoding='utf-8'))
        runs = runs if isinstance(runs, list) else [runs]
        for r in runs:
            if r.get('run_id') == rec.get('run_id') and r.get('split'):
                return Path(r['split'])
        return Path(runs[-1]['split'])
    except (OSError, ValueError, KeyError, IndexError):
        return resolve(given or '.')


def rank(rec):
    """Best record of a question first: fewest calls, fewest failed turns, then run order."""
    failed = sum(1 for x in teacher_turns(rec) if x['why'] == 'failed_turn' or x['why'] == 'invalid')
    return (rec.get('calls') or 99, failed)


def _write_jsonl(path: Path, rows):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def _sha256(path: Path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _norm(text):
    return ' '.join(text.split())


def build(runs, out, *, prompts='current', val_shops=DEFAULT_VAL_SHOPS, val_industries=(), val_families=(),
          val_frac=0.0, max_len=DEFAULT_MAX_LEN, per_question=1, per_group=None, cap_intent=None, drop_weak=(), explore=True,
          drop_drift=False, tokenizer=None, require_exact=False, seed=0, cache_dir=None, validate=True, quiet=False,
          argv=None):
    """Build the package in `out` from teacher run folders; returns stats (also written to stats.json)."""
    t0 = time.monotonic()
    runs, out = [Path(r) for r in runs], Path(out)
    if prompts not in ('current', 'recorded'):
        raise ValueError(f'prompts: current or recorded, not {prompts!r}')
    for r in runs:
        if forbidden(r.resolve()):
            raise SystemExit(f'{r}: refusing a test-split run as training data')
    out.mkdir(parents=True, exist_ok=True)
    counter = TokenCounter(tokenizer, required=require_exact)
    cache_dir = Path(cache_dir) if cache_dir else ROOT / 'outputs' / 'cache'
    splits = {}
    log = lambda *a: None if quiet else print(*a, file=sys.stderr, flush=True)
    stats = {'schema': PACKAGE_SCHEMA, 'sample_schema': SFT_SCHEMA, 'created_at': now(), 'argv': argv,
             'git': git_info(), 'options': {'prompts': prompts, 'val_shops': list(val_shops), 'val_industries': list(val_industries),
                                            'val_families': list(val_families), 'val_frac': val_frac, 'max_len': max_len,
                                            'per_question': per_question, 'per_group': per_group, 'cap_intent': cap_intent, 'drop_weak': list(drop_weak),
                                            'explore': explore, 'drop_drift': drop_drift, 'seed': seed},
             'tokens': {'counter': counter.name, 'exact': counter.exact, 'why_estimate': counter.why or None},
             'sources': [], 'records': collections.Counter(), 'dropped_records': collections.Counter(),
             'dropped_samples': collections.Counter(), 'prompt': collections.Counter()}

    def split_of(path: Path):
        key = str(path.resolve())
        if key not in splits:
            if forbidden(path.resolve()):
                raise SystemExit(f'{path}: refusing a test split as training data')
            splits[key] = Split(path, cache_dir)
        return splits[key]

    # 1. records -> the best `per_question` correct records of each question
    by_question = collections.defaultdict(list)
    for order, run in enumerate(runs):
        src = {'run': rel(run), 'records': 0, 'outcomes': collections.Counter(), 'run_ids': set(), 'splits': set(),
               'teachers': set()}
        for name, rec in load_records(run):
            if rec is None:
                stats['dropped_records']['unreadable'] += 1
                continue
            src['records'] += 1
            src['outcomes'][rec.get('outcome')] += 1
            src['run_ids'].add(rec.get('run_id'))
            src['teachers'].add((rec.get('input') or {}).get('model'))
            split = run_split(run, rec)
            if forbidden(split.resolve()) or forbidden((rec.get('input') or {}).get('split', '')):
                raise SystemExit(f'{run}/logs/{name}: record from a test split')
            src['splits'].add(rel(split))
            stats['records']['total'] += 1
            if not rec.get('correct'):
                stats['dropped_records'][f"outcome_{rec.get('outcome')}"] += 1
                continue
            stats['records']['correct'] += 1
            by_question[(split.resolve().as_posix(), rec['id'])].append((rank(rec), order, rec.get('sample', 0), run, split, rec))
        stats['sources'].append({k: sorted(v, key=str) if isinstance(v, set) else dict(v) if isinstance(v, collections.Counter) else v
                                 for k, v in src.items()})
    chosen = []
    for key in sorted(by_question):
        recs = sorted(by_question[key], key=lambda x: x[:3])
        chosen += recs[:per_question]
        stats['dropped_records']['per_question'] += max(0, len(recs) - per_question)
    if per_group:                                   # copies of one question (rewrites, reskins): earlier runs first
        by_group = collections.defaultdict(list)    # a split with another rulebook asks another question: own count
        for item in chosen:
            sp = split_of(item[4])
            by_group[(sp.group(item[5]['id']), sp.rulebook_sha())].append(item)
        chosen = []
        for g in sorted(by_group):
            items = sorted(by_group[g], key=lambda x: (x[1], x[0], x[5]['id']))
            chosen += items[:per_group]
            stats['dropped_records']['per_group'] += max(0, len(items) - per_group)
    if cap_intent:
        random.Random(seed).shuffle(chosen)
        per_intent, kept = collections.Counter(), []
        for item in chosen:
            rec, split = item[5], item[4]
            sp = split_of(split)
            intent = sp.info(rec['id'], sp.group(rec['id']))['intent'] or 'unknown'
            if per_intent[intent] >= cap_intent:
                stats['dropped_records']['cap_intent'] += 1
                continue
            per_intent[intent] += 1
            kept.append(item)
        chosen = kept
    chosen.sort(key=lambda x: (x[3].as_posix(), x[5]['_file']))

    # 2-4. samples, prompts, filters
    samples, seen, systems = [], set(), {}
    for _, _, _, run, split_path, rec in chosen:
        split = split_of(split_path)
        try:
            pairs = teacher_samples(rec, run, systems.setdefault(run.as_posix(), {}))
        except ValueError as exc:
            stats['dropped_records']['unusable:' + str(exc).split(':')[0][:50]] += 1
            continue
        if not pairs:
            stats['dropped_records']['no_kept_turn'] += 1
            continue
        turns = teacher_turns(rec) if prompts == 'current' else None
        kept_any = False
        for s in pairs:
            m = s['meta']
            if not explore and not m['final']:
                stats['dropped_samples']['explore'] += 1
                continue
            weak = [w for w in m['weak'] if w in drop_weak]
            if weak:
                stats['dropped_samples']['weak:' + weak[0]] += 1
                continue
            m['prompt_source'] = 'recorded'
            if prompts == 'current':
                try:
                    current = split.rebuild(rec, turns, m['turn'])
                    diff = [i for i, (a, b) in enumerate(zip(current, s['prompt'])) if a != b]
                    if len(current) != len(s['prompt']):
                        diff = diff or [min(len(current), len(s['prompt']))]
                    m['prompt_drift'] = bool(diff)
                    if diff:
                        m['drift_message'] = diff[0]
                        stats['prompt']['drift'] += 1
                        if drop_drift:
                            stats['dropped_samples']['prompt_drift'] += 1
                            continue
                    else:
                        stats['prompt']['same'] += 1
                    s['prompt'], m['prompt_source'] = current, 'current'
                except Exception as exc:                    # noqa: BLE001 - data not loadable here: recorded prompt
                    m['prompt_drift'], m['rebuild_error'] = None, f'{type(exc).__name__}: {exc}'[:200]
                    stats['prompt']['rebuild_failed'] += 1
            completion = s['completion'][0]['content']
            m['prompt_tokens'], m['completion_tokens'] = counter.count(s['prompt'], completion)
            m['total_tokens'] = m['prompt_tokens'] + m['completion_tokens']
            m['tokens_exact'] = counter.exact
            if m['total_tokens'] > max_len:
                stats['dropped_samples']['too_long'] += 1
                continue
            m['prompt_sha1'] = hashlib.sha1(json.dumps(s['prompt'], ensure_ascii=False).encode('utf-8')).hexdigest()
            dedup = (m['prompt_sha1'], _norm(completion))
            if dedup in seen:
                stats['dropped_samples']['duplicate'] += 1
                continue
            seen.add(dedup)
            m['split'], m['run_path'] = rel(split.path), rel(run)
            m['group'] = split.group(m['id'])
            m['shop'] = shop_key(split.path, m['business_id'])
            m.update(split.info(m['id'], m['group']))
            samples.append(s)
            kept_any = True
        stats['records']['kept'] += kept_any

    # 5. train/val: by shop, industry, family, then by question group; whole groups and shops on one side
    def held(m):
        return (matches_shop(m['shop'], val_shops) or (m.get('industry') and m['industry'] in val_industries)
                or (m.get('family') and m['family'] in val_families))
    def drawn(g):                                   # --val-frac: a fixed hash draw per group (failed questions too)
        return val_frac > 0 and int(hashlib.sha1(f'{seed}:{g}'.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < val_frac
    val_groups = {s['meta']['group'] for s in samples if held(s['meta']) or drawn(s['meta']['group'])}
    val_shop_keys = {s['meta']['shop'] for s in samples if held(s['meta'])}
    train = [s for s in samples if s['meta']['group'] not in val_groups and s['meta']['shop'] not in val_shop_keys]
    val = [s for s in samples if s['meta']['group'] in val_groups or s['meta']['shop'] in val_shop_keys]
    rnd = random.Random(seed)
    rnd.shuffle(train)
    rnd.shuffle(val)

    # every question of the held-out shops/groups in the source splits (unbiased accuracy of the trained agent)
    val_questions = []
    for split in splits.values():
        for qid, q in split.questions.items():
            g = split.group(qid)
            info = split.info(qid, g)
            shop = shop_key(split.path, q.get('business_id'))
            if g in val_groups or drawn(g) or shop in val_shop_keys or matches_shop(shop, val_shops) or \
                    (info.get('industry') and info['industry'] in val_industries) or (info.get('family') and info['family'] in val_families):
                val_questions.append({'split': rel(split.path), 'id': qid, 'business_id': q.get('business_id'), 'group': g})

    # 6. write
    for name, rows in (('train', train), ('val', val)):
        _write_jsonl(out / f'{name}.jsonl', ({'id': s['id'], 'prompt': s['prompt'], 'completion': s['completion']} for s in rows))
        _write_jsonl(out / f'{name}_meta.jsonl', ({'key': s['id'], **s['meta']} for s in rows))
    _write_jsonl(out / 'val_questions.jsonl', val_questions)
    if TRAIN_SCRIPT.exists():
        shutil.copyfile(TRAIN_SCRIPT, out / 'sft_lora.py')

    def dist(rows, field):
        return dict(collections.Counter(str(s['meta'].get(field)) for s in rows).most_common())
    lengths = {name: {f: percentiles([s['meta'][f] for s in rows]) for f in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
               for name, rows in (('train', train), ('val', val))}
    stats.update(
        samples={'train': len(train), 'val': len(val), 'train_final': sum(s['meta']['final'] for s in train),
                 'val_final': sum(s['meta']['final'] for s in val)},
        questions={'train': len({s['meta']['id'] for s in train}), 'val': len({s['meta']['id'] for s in val}),
                   'train_groups': len({s['meta']['group'] for s in train}), 'val_groups': len({s['meta']['group'] for s in val}),
                   'val_questions_all': len(val_questions)},
        val_shops=sorted(val_shop_keys),
        lengths=lengths,
        max_total_tokens=max([s['meta']['total_tokens'] for s in samples], default=0),
        distributions={name: {f: dist(rows, f) for f in ('gold_type', 'answer_type', 'final', 'intent', 'business_id', 'turn',
                                                         'reason', 'recovered', 'prompt_drift', 'teacher')}
                       for name, rows in (('train', train), ('val', val))},
        weak={name: dict(collections.Counter(w for s in rows for w in s['meta']['weak'])) for name, rows in (('train', train), ('val', val))},
        records={k: v for k, v in stats['records'].items()},
        dropped_records=dict(stats['dropped_records']), dropped_samples=dict(stats['dropped_samples']),
        prompt=dict(stats['prompt']), seconds=round(time.monotonic() - t0, 1))
    readme = README_TEMPLATE.read_text(encoding='utf-8') if README_TEMPLATE.exists() else '# DataMate SFT package\n'
    fill = {'created_at': stats['created_at'], 'train': len(train), 'val': len(val), 'runs': ', '.join(r.as_posix() for r in runs),
            'max_len': max_len, 'max_total': stats['max_total_tokens'], 'counter': counter.name,
            'p99_total': (lengths['train'].get('total_tokens') or {}).get('p99', 0), 'val_shops': ', '.join(sorted(val_shop_keys)) or 'none',
            'commit': (stats['git'] or {}).get('commit') or '?', 'train_len': _suggest_len(stats['max_total_tokens'])}
    for k, v in fill.items():
        readme = readme.replace('{{' + k + '}}', str(v))
    (out / 'README.md').write_text(readme, encoding='utf-8')
    stats['files'] = {p.name: {'bytes': p.stat().st_size, 'sha256': _sha256(p)} for p in sorted(out.iterdir())
                      if p.is_file() and p.name != 'stats.json' and not p.name.endswith('.tmp')}
    if validate:
        from gen.validate import check
        report = check(out, stats=stats)
        stats['validation'] = {'ok': report['ok'], 'errors': report['errors'][:20], 'warnings': report['warnings'][:20]}
    (out / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    log(f"package: train {len(train)} / val {len(val)} samples from {stats['records'].get('kept', 0)} of "
        f"{stats['records'].get('total', 0)} records ({stats['records'].get('correct', 0)} correct) -> {out}")
    log(f"  tokens {counter.name}: max total {stats['max_total_tokens']} (limit {max_len}); dropped records "
        f"{dict(stats['dropped_records'])} samples {dict(stats['dropped_samples'])}; prompts {dict(stats['prompt'])}")
    if validate:
        log(f"  validation: {'ok' if stats['validation']['ok'] else 'FAILED'}"
            + ''.join(f'\n    error: {e}' for e in stats['validation']['errors'][:5])
            + ''.join(f'\n    warning: {w}' for w in stats['validation']['warnings'][:5]))
    return stats


def _suggest_len(longest):
    """The training max length to use: the longest sample rounded up to a multiple of 1024."""
    return max(1024, -(-longest // 1024) * 1024)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--teacher', nargs='+', required=True, help='teacher run folders (gen.teacher --out)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--prompts', choices=('current', 'recorded'), default='current',
                    help='current: rebuild each prompt with the current agent code (default); recorded: as sent')
    ap.add_argument('--drop-drift', action='store_true', help='drop samples whose recorded prompt differs from the current one')
    ap.add_argument('--val-shops', default=','.join(DEFAULT_VAL_SHOPS),
                    help='held-out shops: business ids or split/data/<id> paths, comma separated; "none" for none')
    ap.add_argument('--val-industries', default='', help='held-out industries (synthetic splits with meta.jsonl)')
    ap.add_argument('--val-families', default='', help='held-out export families (synthetic splits with meta.jsonl)')
    ap.add_argument('--val-frac', type=float, default=0.0, help='also hold out this fraction of the other question groups')
    ap.add_argument('--max-len', type=int, default=DEFAULT_MAX_LEN, help='drop samples longer than this (Gemma tokens, prompt + completion)')
    ap.add_argument('--per-question', type=int, default=1, help='records kept per question id (several runs or --samples)')
    ap.add_argument('--per-group', type=int, help='at most this many records per question group (a question and its copies)')
    ap.add_argument('--cap-intent', type=int, help='at most this many records per intent')
    ap.add_argument('--drop-weak', default='', help='drop flagged records: unanswerable,boolean,zero,no_program')
    ap.add_argument('--no-explore', action='store_true', help='final turns only')
    ap.add_argument('--tokenizer', help='folder with tokenizer.json + chat_template.jinja (default: $DM_TOKENIZER or outputs/tokenizers/gemma-4-12B-it)')
    ap.add_argument('--require-exact', action='store_true', help='fail instead of estimating token counts')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--no-validate', action='store_true')
    a = ap.parse_args(argv)
    split = lambda s: tuple(x.strip() for x in s.split(',') if x.strip() and x.strip() != 'none')
    stats = build(a.teacher, a.out, prompts=a.prompts, val_shops=split(a.val_shops), val_industries=split(a.val_industries),
                  val_families=split(a.val_families), val_frac=a.val_frac, max_len=a.max_len, per_question=a.per_question,
                  per_group=a.per_group,
                  cap_intent=a.cap_intent, drop_weak=split(a.drop_weak), explore=not a.no_explore, drop_drift=a.drop_drift,
                  tokenizer=a.tokenizer, require_exact=a.require_exact, seed=a.seed, validate=not a.no_validate,
                  argv=sys.argv if argv is None else argv)
    if not a.no_validate and not stats['validation']['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
