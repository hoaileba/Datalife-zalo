"""Teacher data generation: run the v4 agent (solve) over a split with many threads; one JSON per question (per
sample), written atomically the moment it finishes, with everything needed for statistics and SFT preprocessing later.

Per record (<out>/logs/<id>[__s<k>].json): the question, the gold, the input settings (split, config hash, system prompt
hash, rulebook stats), every model call (the exact messages sent, request settings, output text, thinking, finish,
usage incl. cache/reasoning tokens, timings, response ids, retried errors, cost when prices are given), the solve trace
(programs, sandbox results, observations), the final answer, correctness and totals. The record is a superset of a runner
log, so `python -m gen.sft --run <out> --split <split>` works on it unchanged.

Run folder: run.json (args, config, git commit, versions, balance before/after), config.yaml, system_prompt.md,
logs/*.json, index.jsonl (one compact row per finished record), errors.jsonl (host failures), summary.json.
Interrupt (Ctrl-C) or a budget stop is safe: --resume skips the records already written.

  PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
  $PY -m gen.teacher --split data_gen/train_aug --config config.deepseek_direct.yaml --out outputs/teacher/aug_v1 \
      --limit 200 --workers 8 --price 0.07,0.007,0.28 --max-usd 2 --yes
  $PY -m gen.teacher_stats outputs/teacher/aug_v1            # summary + flat questions.csv / calls.csv
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import yaml  # noqa: E402

from datamate.answer import submission_line  # noqa: E402
from datamate.config import load_config, load_dotenv  # noqa: E402
from datamate.eval import correct, format_ok  # noqa: E402
from datamate.llm import LLM  # noqa: E402
from datamate.runner import Businesses, load_rulebook, read_jsonl, writable_dir  # noqa: E402
from datamate.solve import Context, solve  # noqa: E402

SCHEMA = 'teacher_record/v1'
TEST_SPLITS = ('public_test', 'private_test')
DEFAULT_URLS = (('OPENROUTER', 'https://openrouter.ai/api/v1'), ('DEEPSEEK', 'https://api.deepseek.com'))
CALLS_PER_QUESTION, SECONDS_PER_CALL = 1.1, 25.0          # estimate only (DeepSeek flash runs, 11/11)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    os.replace(tmp, path)


def git_info():
    def git(*a):
        try:
            return subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:                                   # noqa: BLE001
            return None
    return {'commit': git('rev-parse', 'HEAD'), 'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
            'dirty_files': [l.split(maxsplit=1)[-1] for l in (git('status', '--porcelain') or '').splitlines()]}


def versions():
    out = {'python': platform.python_version()}
    for name in ('openai', 'pandas', 'numpy'):
        try:
            out[name] = __import__(name).__version__
        except Exception:                                   # noqa: BLE001
            out[name] = None
    return out


def balance(base_url, key):
    """DeepSeek /user/balance or OpenRouter /credits (best effort, None elsewhere): the real spend of a run."""
    if not base_url or not key:
        return None
    root = base_url.rstrip('/')
    url = root + '/credits' if 'openrouter' in root else root.removesuffix('/v1') + '/user/balance' if 'deepseek' in root else None
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {key}'})
        with urllib.request.urlopen(req, timeout=15) as r:
            return {'at': now(), 'url': url, 'body': json.loads(r.read().decode())}
    except Exception as exc:                                # noqa: BLE001
        return {'at': now(), 'url': url, 'error': f'{type(exc).__name__}: {exc}'[:300]}


class Prices:
    """USD per 1M tokens: input (cache miss), input cache hit, output (thinking included)."""
    def __init__(self, spec):
        self.on = bool(spec)
        self.miss, self.hit, self.out = (float(x) for x in spec.split(',')) if spec else (0.0, 0.0, 0.0)

    def tokens(self, usage):
        u = usage or {}
        prompt, out = u.get('prompt_tokens') or 0, u.get('completion_tokens') or 0
        details = u.get('prompt_tokens_details') or {}
        hit = u.get('prompt_cache_hit_tokens') or details.get('cached_tokens') or 0
        reasoning = (u.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0
        return {'prompt': prompt, 'cache_hit': hit, 'cache_miss': max(0, prompt - hit), 'completion': out, 'reasoning': reasoning}

    def cost(self, usage):
        t = self.tokens(usage)
        return round((t['cache_miss'] * self.miss + t['cache_hit'] * self.hit + t['completion'] * self.out) / 1e6, 8) if self.on else None


class Recorder:
    """The LLM seen by one question: forwards to the shared client and keeps each call (exact messages, reply, error)."""
    def __init__(self, llm, system_sha, inline_system):
        self.llm, self.system_sha, self.inline_system, self.calls = llm, system_sha, inline_system, []

    def _messages(self, messages):
        if self.inline_system:
            return messages
        return [{'role': 'system', 'content_ref': 'system_prompt.md', 'content_sha256': sha(m['content']), 'chars': len(m['content'])}
                if m['role'] == 'system' and sha(m['content']) == self.system_sha else m for m in messages]

    def chat(self, messages, **kw):
        call = {'index': len(self.calls), 'sent_at': now(), 'messages': self._messages(messages),
                'message_chars': [len(m.get('content') or '') for m in messages]}
        self.calls.append(call)
        t0 = time.monotonic()
        try:
            reply = self.llm.chat(messages, **kw)
        except Exception as exc:
            call.update(error=f'{type(exc).__name__}: {exc}'[:2000], seconds=round(time.monotonic() - t0, 3))
            raise
        call.update(output=reply.text, reasoning=reply.reasoning, finish=reply.finish, usage=reply.usage,
                    seconds=reply.seconds, meta=reply.meta, output_chars=len(reply.text), reasoning_chars=len(reply.reasoning))
        return reply


def select_questions(split: Path, a):
    qs = read_jsonl(split / 'questions.jsonl')
    if a.business:
        qs = [q for q in qs if q.get('business_id') in set(a.business)]
    if a.ids or a.ids_file:
        want = set(a.ids or []) | ({l.strip() for l in open(a.ids_file, encoding='utf-8') if l.strip()} if a.ids_file else set())
        qs = [q for q in qs if q.get('id') in want]
    random.Random(a.seed).shuffle(qs)
    if a.limit:
        qs = qs[:a.limit]
    if a.shard:
        k, n = (int(x) for x in a.shard.split('/'))
        qs = [q for i, q in enumerate(sorted(qs, key=lambda q: q['id'])) if i % n == k]
    seen, out = set(), []
    for q in qs:
        if q.get('id') and q['id'] not in seen:
            seen.add(q['id'])
            out.append(q)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--split', required=True, help='folder with questions.jsonl, rulebook.md, calendar.csv, data/ (answers.jsonl optional)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--config', default=str(ROOT / 'config.deepseek_direct.yaml'))
    ap.add_argument('--limit', type=int, help='first N after the seeded shuffle')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--seed', type=int, default=0, help='shuffle seed of the selection')
    ap.add_argument('--ids', nargs='*')
    ap.add_argument('--ids-file')
    ap.add_argument('--business', nargs='*')
    ap.add_argument('--shard', help='k/n: this process takes every n-th question from k (several machines/keys)')
    ap.add_argument('--samples', type=int, default=1, help='runs per question (sample k uses seed config.seed + k)')
    ap.add_argument('--temperature', type=float, help='override llm.temperature (use > 0 with --samples)')
    ap.add_argument('--workers', type=int, help='question threads (default: config run.workers)')
    ap.add_argument('--concurrency', type=int, help='parallel model requests (default: config llm.max_concurrency)')
    ap.add_argument('--max-calls', type=int, help='override agent.max_calls')
    ap.add_argument('--price', help='USD per 1M tokens: input_miss,input_hit,output (cost per call and budget)')
    ap.add_argument('--max-usd', type=float, help='stop starting new questions once the estimated cost reaches this (needs --price)')
    ap.add_argument('--inline-system', action='store_true', help='store the full system prompt in every call (default: a reference + sha256)')
    ap.add_argument('--resume', action='store_true', help='skip records already in <out>/logs')
    ap.add_argument('--allow-test', action='store_true', help='allow public_test/private_test splits')
    ap.add_argument('--yes', action='store_true', help='confirm a run larger than the dev limit (approved by the user)')
    ap.add_argument('--dry-run', action='store_true', help='print the selection and the estimate, no model calls')
    a = ap.parse_args(argv)

    split, out = Path(a.split), Path(a.out)
    if any(t in str(split.resolve()) for t in TEST_SPLITS) and not a.allow_test:
        raise SystemExit('refusing a test split for training data (pass --allow-test only with explicit permission)')
    if not (a.limit or a.all or a.ids or a.ids_file):
        raise SystemExit('choose the questions: --limit N, --all, --ids or --ids-file')
    load_dotenv()
    cfg = load_config(a.config)
    llm_cfg = cfg['llm']
    if a.temperature is not None:
        llm_cfg['temperature'] = a.temperature
    if a.concurrency:
        llm_cfg['max_concurrency'] = a.concurrency
    if a.max_calls:
        cfg['agent']['max_calls'] = a.max_calls
    workers = a.workers or cfg['run']['workers']
    if not os.environ.get(llm_cfg['base_url_env']):
        env = llm_cfg['base_url_env'].upper()
        default = next((url for tag, url in DEFAULT_URLS if tag in env), None)
        if not default:
            raise SystemExit(f"set {llm_cfg['base_url_env']} (base URL of the model server)")
        os.environ[llm_cfg['base_url_env']] = default

    questions = select_questions(split, a)
    jobs = [(q, k) for q in questions for k in range(a.samples)]
    name = lambda q, k: f"{q['id']}.json" if a.samples == 1 else f"{q['id']}__s{k}.json"
    (out / 'logs').mkdir(parents=True, exist_ok=True)
    if out.joinpath('logs').exists() and any((out / 'logs').glob('*.json')) and not a.resume and not a.dry_run:
        raise SystemExit(f'{out}/logs already has records: pass --resume or choose another --out')
    todo = [(q, k) for q, k in jobs if not (out / 'logs' / name(q, k)).exists()]
    est_calls = round(len(todo) * CALLS_PER_QUESTION)
    est_min = round(est_calls * SECONDS_PER_CALL / max(1, min(workers, llm_cfg['max_concurrency'])) / 60, 1)
    print(json.dumps({'questions': len(questions), 'samples': a.samples, 'todo': len(todo), 'done_before': len(jobs) - len(todo),
                      'est_calls': est_calls, 'est_minutes': est_min, 'workers': workers, 'model': llm_cfg['model']}, ensure_ascii=False))
    if a.dry_run:
        return
    if len(todo) > cfg['run'].get('dev_limit', 6) and not a.yes:
        raise SystemExit(f"{len(todo)} runs > dev limit {cfg['run'].get('dev_limit', 6)}: pass --yes once the user approved it")

    rulebook, rulebook_stats, changed, system = load_rulebook(split / 'rulebook.md')
    system_sha = sha(system)
    gold = {g['id']: g for g in read_jsonl(split / 'answers.jsonl')} if (split / 'answers.jsonl').exists() else {}
    cfg_text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
    (out / 'config.yaml').write_text(cfg_text, encoding='utf-8')
    (out / 'system_prompt.md').write_text(system, encoding='utf-8')
    base_url, key = os.environ.get(llm_cfg['base_url_env']), os.environ.get(llm_cfg.get('api_key_env', ''))
    run_id = f"{out.name}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_info = {'run_id': run_id, 'started_at': now(), 'argv': sys.argv, 'args': vars(a), 'split': str(split.resolve()),
                'config_path': str(Path(a.config).resolve()), 'config': cfg, 'config_sha256': sha(cfg_text),
                'system_prompt_sha256': system_sha, 'system_prompt_chars': len(system), 'rulebook': rulebook_stats,
                'rulebook_changes': changed, 'base_url': base_url, 'api_key_env': llm_cfg.get('api_key_env'),
                'git': git_info(), 'versions': versions(), 'host': socket.gethostname(), 'workers': workers,
                'prices_usd_per_1m': {'miss': Prices(a.price).miss, 'hit': Prices(a.price).hit, 'out': Prices(a.price).out} if a.price else None,
                'n_questions': len(questions), 'n_todo': len(todo), 'balance_before': balance(base_url, key)}
    runs = json.loads((out / 'run.json').read_text(encoding='utf-8')) if (out / 'run.json').exists() else []
    runs = runs if isinstance(runs, list) else [runs]
    runs.append(run_info)
    write_json(out / 'run.json', runs)

    try:                                                   # fail fast: wrong URL/key/model never reaches the threads
        LLM({**llm_cfg, 'extra_body': {}, 'max_concurrency': 1}).chat([{'role': 'user', 'content': 'ok'}], max_tokens=1,
                                                                       deadline=time.monotonic() + 60)
    except Exception as exc:                               # noqa: BLE001
        raise SystemExit(f'preflight call to {base_url} failed: {type(exc).__name__}: {str(exc)[:300]}')
    prices = Prices(a.price)
    cache = Path(cfg['run']['cache_dir']); cache = cache if cache.is_absolute() else ROOT / cache
    businesses = Businesses(split, rulebook, writable_dir(cache, out / 'cache'), changed)
    shared = {}                                            # one client per sample seed (seed is part of the request)
    def client(k):
        if k not in shared:
            shared[k] = LLM({**llm_cfg, 'seed': llm_cfg['seed'] + k})
        return shared[k]
    for k in range(a.samples):
        client(k)
    if a.samples > 1:                                      # one concurrency cap across all sample clients
        sem = threading.BoundedSemaphore(llm_cfg['max_concurrency'])
        for c in shared.values():
            c.slots = sem

    lock, stop = threading.Lock(), threading.Event()
    stats = {'done': 0, 'correct': 0, 'wrong': 0, 'abstain': 0, 'no_gold': 0, 'host_error': 0, 'calls': 0,
             'prompt_tokens': 0, 'completion_tokens': 0, 'cost_usd': 0.0}
    t_start = time.monotonic()
    index = open(out / 'index.jsonl', 'a', encoding='utf-8')
    errors = open(out / 'errors.jsonl', 'a', encoding='utf-8')

    def one(job):
        q, k = job
        if stop.is_set():
            return
        t0, started_at = time.monotonic(), now()
        rec = {'schema': SCHEMA, 'run_id': run_id, 'id': q['id'], 'sample': k, 'business_id': q.get('business_id'),
               'question': q.get('question'), 'as_of': q.get('as_of_date'), 'question_row': q,
               'gold': gold.get(q['id']),
               'input': {'split': str(split), 'config_sha256': run_info['config_sha256'], 'system_prompt_sha256': system_sha,
                         'model': llm_cfg['model'], 'temperature': llm_cfg.get('temperature'), 'seed': llm_cfg['seed'] + k,
                         'max_calls': cfg['agent']['max_calls'], 'max_tokens': llm_cfg['max_tokens'],
                         'extra_body': llm_cfg.get('extra_body'), 'rulebook': rulebook_stats},
               'started_at': started_at, 'thread': threading.current_thread().name}
        recorder = Recorder(client(k), system_sha, a.inline_system)
        try:
            business, catalog, path = businesses.get(q['business_id'])
            rec['input'].update(catalog_sha256=sha(json.dumps(catalog, ensure_ascii=False, sort_keys=True, default=str)),
                                catalog_chars=len(json.dumps(catalog, ensure_ascii=False, default=str)))
            result = solve({'id': q['id'], 'question': q['question'], 'as_of': q['as_of_date']},
                           Context(recorder, catalog, business, str(path), cfg, system),
                           t0 + cfg['agent']['question_seconds'])
            kind, answer = result.answer_type, result.answer
            rec.update(reason=result.reason, calls=result.calls, trace=result.trace)
        except Exception:                                  # noqa: BLE001 - host failure: recorded, the run goes on
            kind, answer = 'abstain', None
            rec.update(reason='host_error', error=traceback.format_exc()[-5000:], trace=[], calls=len(recorder.calls))
        line = submission_line(q['id'], kind, answer)
        if not format_ok(line):
            rec['raw_answer'] = {'type': kind, 'answer': answer}
            line, rec['reason'] = submission_line(q['id'], 'abstain'), 'format_guard'
        g = gold.get(q['id'])
        ok = None if g is None else (None if line['type'] == 'abstain' else correct(line, g))
        for c in recorder.calls:
            c['tokens'] = prices.tokens(c.get('usage'))
            c['cost_usd'] = prices.cost(c.get('usage'))
        tok = [c['tokens'] for c in recorder.calls]
        execs = [e for e in rec['trace'] if e.get('event') == 'execution']
        rec.update(type=line['type'], answer=line['answer'], correct=ok,
                   outcome='no_gold' if g is None else 'abstain' if line['type'] == 'abstain' else 'correct' if ok else 'wrong',
                   llm_calls=recorder.calls, finished_at=now(), seconds=round(time.monotonic() - t0, 3),
                   totals={'llm_calls': len(recorder.calls), 'llm_errors': sum('error' in c for c in recorder.calls),
                           'llm_seconds': round(sum(c.get('seconds') or 0 for c in recorder.calls), 3),
                           **{f'{n}_tokens': sum(t[n] for t in tok) for n in ('prompt', 'cache_hit', 'cache_miss', 'completion', 'reasoning')},
                           'output_chars': sum(c.get('output_chars') or 0 for c in recorder.calls),
                           'reasoning_chars': sum(c.get('reasoning_chars') or 0 for c in recorder.calls),
                           'finishes': [c.get('finish') for c in recorder.calls],
                           'programs': len(execs), 'programs_failed': sum(not e['ok'] for e in execs),
                           'explores': sum(bool(e.get('explore')) for e in execs),
                           'exec_seconds': round(sum(e.get('seconds') or 0 for e in execs), 3),
                           'cost_usd': round(sum(c['cost_usd'] or 0 for c in recorder.calls), 8) if prices.on else None})
        row = {'id': q['id'], 'sample': k, 'file': name(q, k), 'business_id': q.get('business_id'), 'gold_type': (g or {}).get('type'),
               'type': line['type'], 'outcome': rec['outcome'], 'reason': rec.get('reason'), 'seconds': rec['seconds'],
               **{x: rec['totals'][x] for x in ('llm_calls', 'prompt_tokens', 'cache_hit_tokens', 'completion_tokens',
                                                'reasoning_tokens', 'programs', 'programs_failed', 'cost_usd')}}
        with lock:
            write_json(out / 'logs' / name(q, k), rec)
            index.write(json.dumps(row, ensure_ascii=False) + '\n'); index.flush()
            if rec.get('reason') == 'host_error':
                errors.write(json.dumps({'id': q['id'], 'sample': k, 'error': rec['error']}, ensure_ascii=False) + '\n'); errors.flush()
            s = stats
            s['done'] += 1
            s[rec['outcome'] if rec['outcome'] in s else 'abstain'] += 1
            s['host_error'] += rec.get('reason') == 'host_error'
            s['calls'] += len(recorder.calls)
            s['prompt_tokens'] += rec['totals']['prompt_tokens']; s['completion_tokens'] += rec['totals']['completion_tokens']
            s['cost_usd'] = round(s['cost_usd'] + (rec['totals']['cost_usd'] or 0), 6)
            el = time.monotonic() - t_start
            eta = el / s['done'] * (len(todo) - s['done'])
            graded = s['correct'] + s['wrong'] + s['abstain']
            print(f"[{s['done']}/{len(todo)}] correct {s['correct']}/{graded} wrong {s['wrong']} abstain {s['abstain']} "
                  f"host_err {s['host_error']} calls {s['calls']} tok {s['prompt_tokens']}/{s['completion_tokens']}"
                  + (f" ${s['cost_usd']:.4f}" if prices.on else '') + f" | {el / 60:.1f}m eta {eta / 60:.1f}m",
                  file=sys.stderr, flush=True)
            if a.max_usd is not None and prices.on and s['cost_usd'] >= a.max_usd and not stop.is_set():
                print(f'budget {a.max_usd} USD reached: no new questions start (resume later with --resume)', file=sys.stderr)
                stop.set()

    def interrupt(*_):
        if stop.is_set():                                  # second Ctrl-C: leave now (finished records are on disk)
            os._exit(130)
        print('interrupt: finishing the running questions, no new ones (resume with --resume)', file=sys.stderr)
        stop.set()
    signal.signal(signal.SIGINT, interrupt)
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='q') as pool:
            list(pool.map(one, todo))
    finally:
        index.close(); errors.close()
        summary = {'run_id': run_id, 'finished_at': now(), 'stopped_early': stop.is_set(),
                   'seconds': round(time.monotonic() - t_start, 1), **stats,
                   'balance_after': balance(base_url, key)}
        graded = stats['correct'] + stats['wrong'] + stats['abstain']
        summary['pa'] = round((stats['correct'] - stats['wrong']) / graded, 4) if graded else None
        runs[-1].update(summary=summary)
        write_json(out / 'run.json', runs)
        write_json(out / 'summary.json', summary)
        print(json.dumps({k: v for k, v in summary.items() if k != 'balance_after'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
