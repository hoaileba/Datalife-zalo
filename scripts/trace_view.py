"""Local trace viewer for outputs/runs: live (polls the files), stdlib only.

Run:  PYTHONPATH=src python scripts/trace_view.py [--port 8765]   then open http://localhost:8765
Reads outputs/runs/<run>/{logs/*.json, summary.json} and the split's questions.jsonl / answers.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from datamate.eval import correct

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'outputs' / 'runs'
_cache: dict = {}

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
    s = _load(RUNS / run / 'summary.json')
    if s and s.get('split'):
        p = Path(s['split'])
        return p if p.is_absolute() else ROOT / p
    return ROOT / 'data' / ('public_test' if run.startswith('p') else 'train')

def _by_id(path: Path):
    return {r['id']: r for r in (_load(path, 'jsonl') or [])}

def _mark(log, gold):
    g = gold.get(log['id'])
    if not g:
        return ''
    if log.get('type') == 'abstain':
        return 'abstain'
    return 'ok' if correct({'type': log.get('type'), 'answer': log.get('answer')}, g) else 'wrong'

def runs():
    out = []
    for d in RUNS.iterdir():
        if not d.is_dir():
            continue
        logs = d / 'logs'
        n = len(os.listdir(logs)) if logs.is_dir() else 0
        s = _load(d / 'summary.json') or {}
        out.append({'name': d.name, 'mtime': max(d.stat().st_mtime, logs.stat().st_mtime if logs.is_dir() else 0),
                    'done': n, 'running': not s, 'score': s.get('score'), 'n': s.get('n')})
    return sorted(out, key=lambda r: -r['mtime'])

def run(name):
    split = _split(name)
    qs, gold = _by_id(split / 'questions.jsonl'), _by_id(split / 'answers.jsonl')
    rows = []
    for f in (RUNS / name / 'logs').glob('*.json'):
        log = _load(f)
        if not log:
            continue
        q = qs.get(log['id'], {})
        rows.append({'id': log['id'], 'question': q.get('question', ''), 'business_id': log.get('business_id'),
                     'reason': log.get('reason'), 'type': log.get('type'), 'answer': log.get('answer'),
                     'calls': log.get('calls'), 'seconds': log.get('seconds'), 'mark': _mark(log, gold),
                     'errors': sum(_failed(e, log.get('trace', [])) for e in log.get('trace', [])),
                     'mtime': f.stat().st_mtime})
    rows.sort(key=lambda r: r['mtime'])
    return {'summary': _load(RUNS / name / 'summary.json'), 'rows': rows}

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
    log = _load(RUNS / name / 'logs' / f'{qid}.json') or {}
    trace = log.get('trace', [])
    for e in trace:                                  # the viewer shows explore errors from their observation
        if e['event'] == 'execution' and e.get('explore'):
            e['failed'] = _failed(e, trace)
            obs = next((o['observation'] for o in trace if o['event'] == 'observation' and o.get('turn') == e.get('turn')), {})
            if e['failed'] and 'error' not in e:
                e['error'] = obs.get('error')
    gold = _by_id(split / 'answers.jsonl')
    return {'log': log, 'q': _by_id(split / 'questions.jsonl').get(qid), 'gold': gold.get(qid), 'mark': _mark(log, gold) if log else ''}

_biz: dict = {}


def _run_config(name):
    """The config a run used: outputs/runs/<run>/config.yaml when saved, else the current config.yaml."""
    from datamate.config import load_config
    saved = RUNS / name / 'config.yaml'
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
    split, log = _split(name), _load(RUNS / name / 'logs' / f'{qid}.json') or {}
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
    saved = RUNS / name / 'system_prompt.md'
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
                data = run(Path(a['name']).name)
            elif u.path == '/api/input':
                data = model_input(Path(a['run']).name, Path(a['id']).name, int(a.get('turn', 0)))
            elif u.path == '/api/q':
                data = question(Path(a['run']).name, Path(a['id']).name)
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
