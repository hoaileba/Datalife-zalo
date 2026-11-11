"""Local trace viewer for outputs/runs and outputs/teacher: live (polls the files), stdlib only.

Run:  PYTHONPATH=src python scripts/trace_view.py [--port 8765]   then open http://localhost:8765
Reads outputs/runs/<run>/{logs/*.json, summary.json} and the split's questions.jsonl / answers.jsonl, and teacher runs
outputs/teacher/<run>/{logs/*.json, index.jsonl, run.json, sft/} (listed as `teacher/<run>`): PA counted live from the
finished records, the exact messages each call sent, and the SFT samples a record gives (gen.sft).
"""
from __future__ import annotations

import argparse
import json
import os
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
    """A run name from the client: <run> or teacher/<run>, one folder, nothing else."""
    if name.startswith(TP):
        return TP + Path(name[len(TP):]).name
    return Path(name).name


def _dir(name: str) -> Path:
    return TEACHER / name[len(TP):] if name.startswith(TP) else RUNS / name


def _log_name(qid: str) -> str:
    return f'{Path(qid).name}.json'


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
    return ROOT / 'data' / ('public_test' if run.startswith('p') else 'train')

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
        for d in base.iterdir():
            if not d.is_dir():
                continue
            logs = d / 'logs'
            n = len(os.listdir(logs)) if logs.is_dir() else 0
            mtime = max(d.stat().st_mtime, logs.stat().st_mtime if logs.is_dir() else 0)
            if kind == 'teacher':
                rows = _teacher_index(d)
                sft_stats = _sft_stats(d) or {}
                out.append({'name': TP + d.name, 'kind': kind, 'mtime': mtime, 'done': len(rows), 'running': _teacher_running(d),
                            'score': _live([OUTCOME_MARK.get(r.get('outcome'), '') for r in rows if r.get('outcome') in OUTCOME_MARK]),
                            'cost': round(sum(r.get('cost_usd') or 0 for r in rows), 4), 'sft': sft_stats.get('samples')})
                continue
            s = _load(d / 'summary.json') or {}
            score = s.get('score')
            if not s and n:                             # running: PA of the questions finished so far
                score = _live([x['mark'] for x in run(d.name)['rows'] if x['mark']])
            out.append({'name': d.name, 'kind': kind, 'mtime': mtime, 'done': n, 'running': not s, 'score': score, 'n': s.get('n')})
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
                     'cost': (log.get('totals') or {}).get('cost_usd'), 'mtime': f.stat().st_mtime})
    rows.sort(key=lambda r: r['mtime'])
    summary = _load(d / 'summary.json')
    if teacher:                                     # live while running; the last run's summary otherwise
        summary = {**(summary or {}), 'running': _teacher_running(d), 'sft_export': _sft_stats(d),
                   'sft_live': {'samples': sum(r['sft'] or 0 for r in rows), 'records_kept': sum(bool(r['sft']) for r in rows),
                                'records': len(rows)}}
    return {'summary': summary, 'live': _live([x['mark'] for x in rows if x['mark']]), 'teacher': teacher, 'rows': rows}

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
            if u.path == '/api/runs':
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
