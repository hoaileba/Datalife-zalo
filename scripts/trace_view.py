"""Local trace viewer for outputs/runs and outputs/teacher: live (polls the files), stdlib only.

Run:  PYTHONPATH=src python scripts/trace_view.py [--port 8765]   then open http://localhost:8765
Reads outputs/runs/<run>/{logs/*.json, summary.json} and the split's questions.jsonl / answers.jsonl, and teacher runs
outputs/teacher/<run>/{logs/*.json, index.jsonl, run.json, sft/} (listed as `teacher/<run>`): PA counted live from the
finished records, the exact messages each call sent, and the SFT samples a record gives (gen.sft).
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from datamate.eval import correct  # noqa: E402

RUNS = ROOT / 'outputs' / 'runs'
TEACHER = ROOT / 'outputs' / 'teacher'
TP = 'teacher/'                                   # run names of teacher runs: teacher/<folder>
OUTCOME_MARK = {'correct': 'ok', 'wrong': 'wrong', 'abstain': 'abstain'}
_cache: dict = {}


def _safe(name: str) -> str:
    """A run name from the client: <run>, teacher/<run> or teacher/<group>/<run> (two plain folder names at most)."""
    if name.startswith(TP):
        parts = [p for p in name[len(TP):].split('/') if p and p not in ('.', '..')][-2:]
        return TP + '/'.join(Path(p).name for p in parts)
    return Path(name).name


def _dir(name: str) -> Path:
    return TEACHER / name[len(TP):] if name.startswith(TP) else RUNS / name


def _log_name(qid: str) -> str:
    return f'{Path(qid).name}.json'


PRICE = (0.28, 0.028, 0.42)          # DeepSeek USD per 1M tokens (input miss, input hit, output): scripts/sft_mix.py


def _log_cost(log):
    """USD of a runner log from the usage of its model calls (None when no call reported usage)."""
    usage = [e.get('usage') or {} for e in log.get('trace', []) if e.get('event') == 'model']
    if not any(usage):
        return None
    total = 0.0
    for u in usage:
        hit = u.get('prompt_cache_hit_tokens') or (u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0
        miss = max(0, (u.get('prompt_tokens') or 0) - hit)
        total += miss * PRICE[0] + hit * PRICE[1] + (u.get('completion_tokens') or 0) * PRICE[2]
    return round(total / 1e6, 6)


def _live(marks):
    """PA as the competition scores it: (correct - wrong) / graded."""
    n = len(marks)
    c, w, ab = marks.count('ok'), marks.count('wrong'), marks.count('abstain')
    return {'n': n, 'correct': c, 'wrong': w, 'abstain': ab, 'pa': round((c - w) / n, 4) if n else None}

def _load(path: Path, kind='json'):
    """File content cached by mtime; None if missing/half-written."""
    try:
        m = path.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == m:
        return hit[1]
    try:
        text = path.read_text(encoding='utf-8')
        val = [json.loads(l) for l in text.splitlines() if l.strip()] if kind == 'jsonl' else json.loads(text)
    except (json.JSONDecodeError, OSError):
        return hit[1] if hit else None
    _cache[path] = (m, val)
    return val

def _split(run: str) -> Path:
    if run.startswith(TP):
        info = _load(_dir(run) / 'run.json') or []
        info = (info[-1] if info else {}) if isinstance(info, list) else info
        p = Path(info.get('split') or ROOT / 'data' / 'train')
        return p if p.is_absolute() else ROOT / p
    s = _load(RUNS / run / 'summary.json')
    if s and s.get('split'):
        p = Path(s['split'])
        return p if p.is_absolute() else ROOT / p
    return _split_of_logs(RUNS / run / 'logs') or ROOT / 'data' / ('public_test' if run.startswith('p') else 'train')


def _split_of_logs(logs: Path):
    """A run still going has no summary.json yet: the split whose questions.jsonl holds the id of one of its logs."""
    first = next(iter(sorted(logs.glob('q*.json'))), None) if logs.is_dir() else None
    if first is None:
        return None
    for path in [ROOT / 'data' / 'public_test', ROOT / 'data' / 'train', *sorted((ROOT / 'data_gen').glob('**/questions.jsonl'))]:
        split = path.parent if path.name == 'questions.jsonl' else path
        if first.stem in _by_id(split / 'questions.jsonl'):
            return split
    return None

def _by_id(path: Path):
    return {r['id']: r for r in (_load(path, 'jsonl') or [])}

def _mark(log, gold):
    if 'outcome' in log:                            # teacher record: graded when it was written
        return OUTCOME_MARK.get(log['outcome'], '')
    g = gold.get(log['id'])
    if not g:
        return ''
    if log.get('type') == 'abstain':
        return 'abstain'
    return 'ok' if correct({'type': log.get('type'), 'answer': log.get('answer')}, g) else 'wrong'

def _teacher_index(d: Path):
    """Last row per record file of index.jsonl (a --resume appends)."""
    return list({r.get('file') or r['id']: r for r in (_load(d / 'index.jsonl', 'jsonl') or [])}.values())


def _teacher_running(d: Path):
    info = _load(d / 'run.json') or []
    return bool(isinstance(info, list) and info and 'summary' not in info[-1])


def runs():
    out = []
    for kind, base in (('run', RUNS), ('teacher', TEACHER)):
        if not base.is_dir():
            continue
        dirs = [d for d in base.iterdir() if d.is_dir()]
        if kind == 'teacher':                       # a group of teacher runs (outputs/teacher/final/p1_B2_0, ...)
            dirs = [x for d in dirs for x in ([d] if (d / 'logs').is_dir() else
                                              sorted(c for c in d.iterdir() if c.is_dir() and (c / 'logs').is_dir()))]
        for d in dirs:
            logs = d / 'logs'
            n = sum(1 for _ in logs.glob('*.json')) if logs.is_dir() else 0     # traces only, not answers.jsonl
            mtime = max(d.stat().st_mtime, logs.stat().st_mtime if logs.is_dir() else 0)
            if kind == 'teacher':
                rows = _teacher_index(d)
                sft_stats = _sft_stats(d) or {}
                out.append({'name': TP + d.relative_to(TEACHER).as_posix(), 'kind': kind, 'mtime': mtime, 'done': len(rows), 'running': _teacher_running(d),
                            'score': _live([OUTCOME_MARK.get(r.get('outcome'), '') for r in rows if r.get('outcome') in OUTCOME_MARK]),
                            'cost': round(sum(r.get('cost_usd') or 0 for r in rows), 4), 'sft': sft_stats.get('samples')})
                continue
            s = _load(d / 'summary.json') or {}
            score = s.get('score')
            detail = run(d.name) if n else {'rows': [], 'cost': None}
            if not s and n:                             # running: PA of the questions finished so far
                score = _live([x['mark'] for x in detail['rows'] if x['mark']])
            out.append({'name': d.name, 'kind': kind, 'mtime': mtime, 'done': n, 'running': not s, 'score': score, 'n': s.get('n'),
                        'cost': detail['cost']})
    return sorted(out, key=lambda r: -r['mtime'])

def _sft_stats(d):
    """<run>/sft/stats.json (gen.package layout) as the flat counts the page shows."""
    st = _load(d / 'sft' / 'stats.json')
    if not st:
        return None
    smp, rec = st.get('samples') or {}, st.get('records') or {}
    if not isinstance(smp, dict):                   # old gen.sft export
        return st
    n, fin = smp.get('train', 0) + smp.get('val', 0), smp.get('train_final', 0) + smp.get('val_final', 0)
    return {'samples': n, 'records_kept': rec.get('kept'), 'records': rec.get('total'), 'final': fin, 'explore': n - fin}


def _sft_count(log):
    """Training samples a teacher record gives (the turns gen.sft keeps)."""
    try:
        from gen.sft import teacher_turns
        return sum(x['keep'] for x in teacher_turns(log))
    except Exception:                               # noqa: BLE001
        return None


def run(name):
    split, d = _split(name), _dir(name)
    teacher = name.startswith(TP)
    qs, gold = _by_id(split / 'questions.jsonl'), _by_id(split / 'answers.jsonl')
    rows = []
    for f in (d / 'logs').glob('*.json'):
        log = _load(f)
        if not log:
            continue
        q = qs.get(log['id']) or log.get('question_row') or {}
        rows.append({'id': f.stem, 'question': q.get('question', ''), 'business_id': log.get('business_id'),
                     'reason': log.get('reason'), 'type': log.get('type'), 'answer': log.get('answer'),
                     'calls': log.get('calls'), 'seconds': log.get('seconds'), 'mark': _mark(log, gold),
                     'errors': sum(_failed(e, log.get('trace', [])) for e in log.get('trace', [])),
                     'sft': _sft_count(log) if teacher else None,
                     'cost': (log.get('totals') or {}).get('cost_usd') if teacher else _log_cost(log), 'mtime': f.stat().st_mtime})
    rows.sort(key=lambda r: r['mtime'])
    summary = _load(d / 'summary.json')
    if teacher:                                     # live while running; the last run's summary otherwise
        summary = {**(summary or {}), 'running': _teacher_running(d), 'sft_export': _sft_stats(d),
                   'sft_live': {'samples': sum(r['sft'] or 0 for r in rows), 'records_kept': sum(bool(r['sft']) for r in rows),
                                'records': len(rows)}}
    cost = round(sum(r['cost'] or 0 for r in rows), 4) if any(r['cost'] for r in rows) else None
    return {'summary': summary, 'live': _live([x['mark'] for x in rows if x['mark']]), 'teacher': teacher, 'rows': rows, 'cost': cost}

def _failed(e, trace):
    """A program that really failed. An explore program without `result` ends ok=False (NoResult) and is not an
    error: for explore, the error is the one its observation shows."""
    if e['event'] != 'execution' or e['ok']:
        return False
    if not e.get('explore'):
        return True
    return any(o['event'] == 'observation' and o.get('turn') == e.get('turn') and 'error' in (o.get('observation') or {})
               for o in trace)


def question(name, qid):
    split = _split(name)
    log = _load(_dir(name) / 'logs' / _log_name(qid)) or {}
    trace = log.get('trace', [])
    for e in trace:                                  # the viewer shows explore errors from their observation
        if e['event'] == 'execution' and e.get('explore'):
            e['failed'] = _failed(e, trace)
            obs = next((o['observation'] for o in trace if o['event'] == 'observation' and o.get('turn') == e.get('turn')), {})
            if e['failed'] and 'error' not in e:
                e['error'] = obs.get('error')
    gold = _by_id(split / 'answers.jsonl')
    real = log.get('id', qid)                       # a sample file is <id>__s<k>
    teacher = name.startswith(TP)
    out = {k: v for k, v in log.items() if k != 'llm_calls'}        # calls: /api/input and /api/sft
    return {'log': out, 'q': _by_id(split / 'questions.jsonl').get(real) or log.get('question_row'),
            'gold': gold.get(real) or log.get('gold'), 'mark': _mark(log, gold) if log else '',
            'teacher': teacher, 'sft': _sft_count(log) if teacher and log else None}


def sft(name, qid):
    """The SFT samples a teacher record gives (gen.sft.teacher_samples): what <run>/sft/train.jsonl holds for it."""
    from gen.sft import teacher_samples
    d = _dir(name)
    rec = _load(d / 'logs' / _log_name(qid))
    if not rec:
        return {'error': 'record not found', 'samples': []}
    try:
        samples = teacher_samples(rec, d)
    except ValueError as exc:
        return {'error': str(exc), 'samples': []}
    return {'samples': samples, 'correct': rec.get('correct')}

_biz: dict = {}


def _run_config(name):
    """The config a run used: outputs/runs/<run>/config.yaml when saved, else the current config.yaml."""
    from datamate.config import load_config
    saved = _dir(name) / 'config.yaml'
    return load_config(saved) if saved.exists() else load_config()


def _catalog(split: Path, business_id: str, cfg):
    """(business, catalog) as the runner builds them; cached per (split, business)."""
    from datamate.catalog import build_catalog
    from datamate.data import load_business
    from datamate.runner import load_rulebook
    k = (str(split), business_id)
    if k not in _biz:
        cache = Path(cfg['run']['cache_dir']); cache = cache if cache.is_absolute() else ROOT / cache
        business = load_business(split / 'data' / business_id, split / 'calendar.csv', cache)
        text, _, changed, _ = load_rulebook(split / 'rulebook.md')
        _biz[k] = (business, build_catalog(business, text, changed))
    return _biz[k]


def model_input(name, qid, turn):
    """Messages of model call `turn`, rebuilt with the current prompt code from the logged trace.
    Exact unless the prompt/catalog code or the rulebook changed since; the system prompt is the one the run saved."""
    from datamate import prompt
    from datamate.catalog import lookup
    from datamate.solve import STOPPED, _echo
    split, log = _split(name), _load(_dir(name) / 'logs' / _log_name(qid)) or {}
    if name.startswith(TP):                                          # teacher: the exact messages that call sent
        from gen.sft import _system_text
        calls = [c for c in log.get('llm_calls') or [] if 'error' not in c]
        if turn >= len(calls):
            return {'error': f'no recorded call for turn {turn}'}
        msgs = []
        for m in calls[turn]['messages']:
            if 'content' not in m:
                m = {'role': m['role'], 'content': _system_text(_dir(name), m.get('content_sha256', ''), {}) or '(system prompt not saved)'}
            msgs.append(m)
        return {'messages': msgs, 'exact': True}
    q = _by_id(split / 'questions.jsonl').get(qid)
    if not q or not log:
        return {'error': 'question or log not found'}
    cfg = _run_config(name)
    business, catalog = _catalog(split, log['business_id'], cfg)
    max_calls = cfg['agent']['max_calls']
    trace = log.get('trace', [])
    obs = {e['turn']: e['observation'] for e in trace if e['event'] == 'observation'}
    outputs = {e['turn']: e for e in trace if e['event'] == 'model'}
    history = []
    for t in range(turn):
        e, terminal = outputs.get(t), t == max_calls - 1
        if e is None or t not in obs:
            break
        try:
            action = {'action': 'invalid'} if e['finish'] in STOPPED else prompt.parse_action(e['output'], terminal)
        except prompt.ActionError:
            action = {'action': 'invalid'}
        history.append((_echo(action), obs[t]))
    msgs = prompt.messages(catalog, q['question'], q['as_of_date'], lookup(q['question'], business), history,
                           max_calls - turn, turn == max_calls - 1)
    saved = _dir(name) / 'system_prompt.md'
    if saved.exists():                                               # the exact system prompt the run used
        msgs[0]['content'] = saved.read_text(encoding='utf-8')
    return {'messages': msgs}


# ---- SFT packages (outputs/sft/<name>): overview + samples, for the final train set
SFT = ROOT / 'outputs' / 'sft'


def _series(run):
    """Source series of a sample from its teacher run folder: p1_B2_3 -> B2, main_reskin_1 -> forced."""
    name = str(run or '').split('/')[-1]
    if name.startswith(('main_', 'extra_', 'pilot_')):
        return 'forced'
    parts = name.split('_')
    return parts[1] if len(parts) > 2 else name


def _pkg(name):
    d = SFT / Path(name).name
    key = ('pkg', d, max((p.stat().st_mtime for p in d.glob('*.jsonl')), default=0))
    if key in _cache:
        return _cache[key]
    sides = {}
    for side in ('train', 'val'):
        f = d / f'{side}.jsonl'
        if not f.exists():
            continue
        offsets, pos = [], 0
        with open(f, 'rb') as fh:
            for line in fh:
                offsets.append(pos)
                pos += len(line)
        meta = [json.loads(l) for l in open(d / f'{side}_meta.jsonl', encoding='utf-8') if l.strip()]
        sides[side] = {'offsets': offsets, 'meta': meta}
    _cache[key] = sides
    return sides


def datasets():
    return [{'name': d.name, 'mtime': d.stat().st_mtime,
             'train': sum(1 for _ in open(d / 'train_meta.jsonl', encoding='utf-8')) if (d / 'train_meta.jsonl').exists() else 0}
            for d in sorted(SFT.iterdir(), key=lambda x: -x.stat().st_mtime) if (d / 'train.jsonl').exists()]


def _pct(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {}
    at = lambda q: xs[min(len(xs) - 1, int(q * len(xs)))]
    return {'n': len(xs), 'mean': round(sum(xs) / len(xs)), 'p50': at(.5), 'p90': at(.9), 'p99': at(.99), 'max': xs[-1], 'sum': sum(xs)}


def dataset(name):
    import collections
    d = SFT / Path(name).name
    out = {'name': d.name, 'sides': {}}
    for side, v in _pkg(name).items():
        m = v['meta']
        c = lambda f: collections.Counter(f(x) for x in m).most_common()
        out['sides'][side] = {
            'n': len(m), 'questions': len({x.get('id') for x in m}),
            'series': c(lambda x: _series(x.get('run'))), 'intent': c(lambda x: x.get('intent') or '?'),
            'answer_type': c(lambda x: x.get('answer_type') or '?'), 'turn': c(lambda x: f"turn {x.get('turn')}" + (' (final)' if x.get('final') else ' (look)')),
            'recovered': c(lambda x: 'after an error/flag' if x.get('turn') else 'first turn'),
            'prompt_tokens': _pct([x.get('prompt_tokens') for x in m]), 'completion_tokens': _pct([x.get('completion_tokens') for x in m])}
    st = d / 'stats.json'
    if st.exists():
        s = json.loads(st.read_text(encoding='utf-8'))
        out['dropped_records'] = sorted(((k, v) for k, v in (s.get('dropped_records') or {}).items() if v), key=lambda x: -x[1])
        out['records'] = s.get('records')
        out['created_at'] = s.get('created_at')
    pf = d / 'POSTFILTER.json'
    if pf.exists():
        out['postfilter'] = len(json.loads(pf.read_text(encoding='utf-8')).get('removed_after_build', []))
    return out


def dataset_rows(name, side, series='', intent='', atype='', turn='', q='', offset=0, limit=300):
    m = _pkg(name)[side]['meta']
    rows = []
    for i, x in enumerate(m):
        if series and _series(x.get('run')) != series or intent and (x.get('intent') or '?') != intent \
                or atype and (x.get('answer_type') or '?') != atype or turn and f"turn {x.get('turn')}" != turn.split(' (')[0] \
                or q and q.lower() not in (str(x.get('question')) + ' ' + str(x.get('id'))).lower():
            continue
        rows.append({'line': i, 'id': x.get('id'), 'series': _series(x.get('run')), 'intent': x.get('intent'),
                     'type': x.get('answer_type'), 'turn': x.get('turn'), 'final': x.get('final'), 'question': x.get('question'),
                     'tok': x.get('total_tokens'), 'business': x.get('business_id')})
    return {'total': len(rows), 'rows': rows[offset:offset + limit]}


def dataset_sample(name, side, line):
    v = _pkg(name)[side]
    with open(SFT / Path(name).name / f'{side}.jsonl', 'rb') as fh:
        fh.seek(v['offsets'][line])
        sample = json.loads(fh.readline())
    return {'sample': sample, 'meta': v['meta'][line]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        a = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == '/':
                return self._send((Path(__file__).parent / 'assets' / 'trace_view.html').read_bytes(), 'text/html; charset=utf-8')
            if u.path == '/data':
                return self._send((Path(__file__).parent / 'assets' / 'dataset_view.html').read_bytes(), 'text/html; charset=utf-8')
            if u.path == '/api/datasets':
                data = datasets()
            elif u.path == '/api/dataset':
                data = dataset(a['name'])
            elif u.path == '/api/dataset_rows':
                data = dataset_rows(a['name'], a.get('side', 'train'), a.get('series', ''), a.get('intent', ''), a.get('type', ''),
                                    a.get('turn', ''), a.get('q', ''), int(a.get('offset', 0)))
            elif u.path == '/api/dataset_sample':
                data = dataset_sample(a['name'], a.get('side', 'train'), int(a['line']))
            elif u.path == '/api/runs':
                data = runs()
            elif u.path == '/api/run':
                data = run(_safe(a['name']))
            elif u.path == '/api/input':
                data = model_input(_safe(a['run']), Path(a['id']).name, int(a.get('turn', 0)))
            elif u.path == '/api/q':
                data = question(_safe(a['run']), Path(a['id']).name)
            elif u.path == '/api/sft':
                data = sft(_safe(a['run']), Path(a['id']).name)
            else:
                self.send_error(404)
                return
            self._send(json.dumps(data, ensure_ascii=False, default=str).encode(), 'application/json')
        except Exception as exc:  # keep the viewer alive
            self._send(json.dumps({'error': f'{type(exc).__name__}: {exc}'}).encode(), 'application/json')

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='127.0.0.1')
    a = ap.parse_args()
    print(f'http://{a.host}:{a.port}')
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
