"""Teacher samples on reskinned shops without the teacher (no model calls): each correct teacher record of a train
question is replayed by the real agent loop (datamate.solve) on the reskinned copy of its shop, with the teacher's
replies mapped to the new names (gen.remap) as a scripted model. Prompts are therefore what the agent sends on the copy
(catalog, data lookup, README, history), and every observation (explore output, errors, checks) is the real output
on the copy's data. The result is a teacher run folder (teacher_record/v1), so gen.package takes it like any run:

    python -m gen.reskin_replay --teacher outputs/teacher/train_v1 --split data_gen/reskin_1 --out outputs/teacher/reskin_1
    python -m gen.package --teacher outputs/teacher/train_v1 outputs/teacher/reskin_1 outputs/teacher/reskin_2 --out ...

A record is kept only when the replay ends like the original (same number of model turns, same status of every
turn's observation, same answer type) and the answer equals the copy's gold; and no reply, after mapping, still
names an old table/column/file/label (gen.remap.NameMap.stale). Dropped records: <out>/dropped.jsonl (reason per
record), counts in <out>/summary.json. Thinking text of the teacher is not copied (it names the old shop).
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

import yaml  # noqa: E402

from datamate import prompt  # noqa: E402
from datamate.answer import submission_line  # noqa: E402
from datamate.config import load_config  # noqa: E402
from datamate.eval import correct, format_ok  # noqa: E402
from datamate.llm import Reply  # noqa: E402
from datamate.runner import Businesses, load_rulebook, read_jsonl  # noqa: E402
from datamate.solve import Context, solve  # noqa: E402
from gen.package import load_records, rank  # noqa: E402
from gen.remap import NameMap  # noqa: E402
from gen.teacher import SCHEMA, Recorder, sha, write_json  # noqa: E402

FORBIDDEN = ('public_test', 'private_test')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(p).as_posix()


def map_output(text: str, nm: NameMap):
    """(mapped reply text, stale references): prose with map_prose, the ```python block with map_code."""
    text = text or ''
    fence = prompt.FENCE.search(text)
    if not fence:
        new = nm.map_prose(text)
        return new, nm.stale(prose=new)
    head, body = text[:fence.start()], text[fence.end():]
    end = body.find('```')
    code, tail = (body[:end], body[end:]) if end >= 0 else (body, '')
    head, code, tail = nm.map_prose(head), nm.map_code(code), nm.map_prose(tail)
    return head + text[fence.start():fence.end()] + code + tail, nm.stale(code=code, prose=head + tail)


class Script:
    """The model of one replay: the mapped teacher replies in order; asking for one more is a divergence."""
    def __init__(self, replies):
        self.replies, self.i = replies, 0

    def chat(self, messages, **kw):
        if self.i >= len(self.replies):
            raise RuntimeError('diverged: the replay asked for more turns than the teacher took')
        r = self.replies[self.i]
        self.i += 1
        return r


def statuses(trace):
    """Per model turn: the status of its observation ('final' when the turn ended the question)."""
    obs = {e['turn']: (e.get('observation') or {}).get('status') for e in trace if e.get('event') == 'observation'}
    turns = sorted(e['turn'] for e in trace if e.get('event') == 'model')
    return [obs.get(t, 'final') for t in turns]


def source_records(runs):
    """Best correct record per (split, question id) over the teacher runs (gen.package.rank)."""
    best = {}
    for order, run in enumerate(runs):
        if any(f in str(Path(run).resolve()) for f in FORBIDDEN):
            raise SystemExit(f'{run}: refusing a test-split run')
        for _, rec in load_records(Path(run)):
            if rec is None or not rec.get('correct'):
                continue
            key = rec['id']
            cand = (rank(rec), order, rec.get('sample', 0), Path(run), rec)
            if key not in best or cand[:3] < best[key][:3]:
                best[key] = cand
    return {k: (v[3], v[4]) for k, v in best.items()}


def replay_one(rec, src_run, q, gold, nm, businesses, system, cfg, run_id, split, system_sha):
    """(record or None, drop reason, detail)."""
    trace = rec.get('trace') or []
    models = [e for e in trace if e.get('event') == 'model']
    replies, stale = [], []
    for e in models:
        text, st = map_output(e.get('output') or '', nm)
        stale += st
        replies.append(Reply(text, e.get('finish'), e.get('usage'), e.get('seconds') or 0.0))
    if stale:
        return None, 'stale_name', sorted(set(stale))[:8]
    business, catalog, path = businesses.get(q['business_id'])
    recorder = Recorder(Script(replies), system_sha, False)
    t0, started = time.monotonic(), now()
    out = solve({'id': q['id'], 'question': q['question'], 'as_of': q['as_of_date']},
                Context(recorder, catalog, business, str(path), cfg, system), t0 + cfg['agent']['question_seconds'])
    line = submission_line(q['id'], out.answer_type, out.answer)
    if not format_ok(line):
        line = submission_line(q['id'], 'abstain')
    ok = line['type'] != 'abstain' and correct(line, gold)
    before, after = statuses(trace), statuses(out.trace)
    if out.reason == 'llm_error':
        return None, 'diverged_more_turns', after
    if before != after:
        return None, 'diverged_turns', {'teacher': before, 'replay': after}
    if line['type'] != rec.get('type'):
        return None, 'diverged_type', {'teacher': rec.get('type'), 'replay': line['type']}
    if not ok:
        return None, 'wrong_on_copy', {'answer': line.get('answer'), 'gold': gold.get('answer')}
    for c in recorder.calls:
        c['reasoning'] = ''
    execs = [e for e in out.trace if e.get('event') == 'execution']
    inp = dict(rec.get('input') or {})
    inp.update(split=rel(split), system_prompt_sha256=system_sha,
               catalog_sha256=sha(json.dumps(catalog, ensure_ascii=False, sort_keys=True, default=str)),
               reskin_of={'run': rel(src_run), 'record': rec.get('_file'), 'split': (rec.get('input') or {}).get('split')})
    new = {'schema': SCHEMA, 'run_id': run_id, 'id': q['id'], 'sample': rec.get('sample', 0),
           'business_id': q['business_id'], 'question': q['question'], 'as_of': q['as_of_date'], 'question_row': q,
           'gold': gold, 'input': inp, 'started_at': started, 'thread': threading.current_thread().name,
           'reason': out.reason, 'calls': out.calls, 'trace': out.trace, 'type': line['type'], 'answer': line['answer'],
           'correct': True, 'outcome': 'correct', 'llm_calls': recorder.calls, 'finished_at': now(),
           'seconds': round(time.monotonic() - t0, 3),
           'totals': {'llm_calls': len(recorder.calls), 'programs': len(execs), 'programs_failed': sum(not e['ok'] for e in execs),
                      'explores': sum(bool(e.get('explore')) for e in execs), 'finishes': [c.get('finish') for c in recorder.calls]},
           'reskin': {'source_run': rel(src_run), 'source_record': rec.get('_file'), 'names': len(nm.names),
                      'labels': len(nm.labels)}}
    return new, None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--teacher', nargs='+', required=True, help='teacher run folders whose correct records are replayed')
    ap.add_argument('--split', required=True, help='a reskinned split (gen.reskin): data_gen/reskin_<k>')
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=4, help='parallel replays (each runs sandbox programs)')
    ap.add_argument('--limit', type=int, help='at most this many records (dev)')
    ap.add_argument('--shops', default='', help='only these shops (comma separated)')
    ap.add_argument('--resume', action='store_true', help='skip questions already in <out>/logs or <out>/dropped.jsonl')
    a = ap.parse_args(argv)
    split, out = Path(a.split), Path(a.out)
    if any(f in str(split.resolve()) for f in FORBIDDEN):
        raise SystemExit('refusing a test split')
    plans = json.loads((split / 'reskin.json').read_text(encoding='utf-8'))['shops']
    questions = {q['id']: q for q in read_jsonl(split / 'questions.jsonl')}
    gold = {g['id']: g for g in read_jsonl(split / 'answers.jsonl')}
    sources = source_records(a.teacher)
    shops = set(s for s in a.shops.split(',') if s)
    todo = sorted(((q['business_id'], qid) for qid, q in questions.items() if qid in sources
                   and (not shops or q['business_id'] in shops)))
    (out / 'logs').mkdir(parents=True, exist_ok=True)
    done = {p.stem for p in (out / 'logs').glob('*.json')}
    if (out / 'dropped.jsonl').exists():
        done |= {json.loads(l)['id'] for l in open(out / 'dropped.jsonl', encoding='utf-8') if l.strip()}
    if done and not a.resume:
        raise SystemExit(f'{out} has records: pass --resume or choose another --out')
    todo = [x for x in todo if x[1] not in done]
    if a.limit:
        todo = todo[:a.limit]
    first_src = sources[todo[0][1]][0] if todo else Path(a.teacher[0])
    cfg = load_config(first_src / 'config.yaml') if (first_src / 'config.yaml').exists() else load_config()
    rulebook, rb_stats, changed, system = load_rulebook(split / 'rulebook.md')
    system_sha = sha(system)
    (out / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (out / 'system_prompt.md').write_text(system, encoding='utf-8')
    (out / 'system_prompts').mkdir(exist_ok=True)
    (out / 'system_prompts' / f'{system_sha[:16]}.md').write_text(system, encoding='utf-8')
    run_id = f"{out.name}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    runs = json.loads((out / 'run.json').read_text(encoding='utf-8')) if (out / 'run.json').exists() else []
    runs.append({'run_id': run_id, 'started_at': now(), 'argv': sys.argv if argv is None else argv,
                 'split': str(split.resolve()), 'teacher_runs': [rel(Path(r)) for r in a.teacher], 'model': 'reskin_replay',
                 'system_prompt_sha256': system_sha, 'rulebook': rb_stats, 'rulebook_changes': changed,
                 'n_todo': len(todo), 'config': cfg})
    write_json(out / 'run.json', runs)
    cache = Path(cfg['run']['cache_dir'])
    cache = cache if cache.is_absolute() else ROOT / cache
    businesses = Businesses(split, rulebook, cache, changed)
    counts, lock = collections.Counter(), threading.Lock()
    dropped_f = open(out / 'dropped.jsonl', 'a', encoding='utf-8')
    index_f = open(out / 'index.jsonl', 'a', encoding='utf-8')
    t_start = time.monotonic()

    def one(item):
        shop, qid = item
        src_run, rec = sources[qid]
        q = questions[qid]
        p = plans.get(shop) or {}
        nm = NameMap(p.get('names') or {}, p.get('label_map') or {}, p.get('keep') or ())
        try:
            new, why, detail = replay_one(rec, src_run, q, gold[qid], nm, businesses, system, cfg, run_id, split, system_sha)
        except Exception as exc:                            # noqa: BLE001 - one record never stops the run
            new, why, detail = None, 'host_error', f'{type(exc).__name__}: {exc}'[:300]
        with lock:
            if new is not None:
                write_json(out / 'logs' / f'{qid}.json', new)
                index_f.write(json.dumps({'id': qid, 'business_id': shop, 'calls': new['calls'], 'type': new['type'],
                                          'source': new['reskin']['source_record']}, ensure_ascii=False) + '\n')
                index_f.flush()
                counts['kept'] += 1
            else:
                dropped_f.write(json.dumps({'id': qid, 'business_id': shop, 'reason': why, 'detail': detail,
                                            'source_run': rel(src_run), 'source_record': rec.get('_file')},
                                           ensure_ascii=False, default=str) + '\n')
                dropped_f.flush()
                counts[why] += 1
            n = sum(counts.values())
            if n % 50 == 0 or n == len(todo):
                el = time.monotonic() - t_start
                print(f'[{n}/{len(todo)}] {dict(counts)} | {el / 60:.1f}m eta {el / n * (len(todo) - n) / 60:.1f}m',
                      file=sys.stderr, flush=True)

    by_shop = collections.defaultdict(list)
    for item in todo:
        by_shop[item[0]].append(item)
    try:
        for shop in sorted(by_shop):
            with ThreadPoolExecutor(max(1, a.workers), thread_name_prefix='r') as pool:
                list(pool.map(one, by_shop[shop]))
            businesses.items.pop(shop, None)            # one shop in memory at a time
    finally:
        dropped_f.close()
        index_f.close()
        kept = len(list((out / 'logs').glob('*.json')))
        reasons = collections.Counter(json.loads(l)['reason'] for l in open(out / 'dropped.jsonl', encoding='utf-8') if l.strip())
        summary = {'run_id': run_id, 'finished_at': now(), 'split': rel(split), 'teacher_runs': [rel(Path(r)) for r in a.teacher],
                   'source_correct_records': len(sources), 'questions_in_split': len(questions),
                   'attempted_total': kept + sum(reasons.values()), 'kept_total': kept, 'dropped_total': dict(reasons),
                   'this_run': dict(counts), 'seconds': round(time.monotonic() - t_start, 1)}
        runs[-1].update(summary=summary)
        write_json(out / 'run.json', runs)
        write_json(out / 'summary.json', summary)
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
