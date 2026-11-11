"""Statistics of teacher runs (gen.teacher): flat tables for preprocessing and a printed summary.

  python -m gen.teacher_stats outputs/teacher/aug_v1 [more runs...] [--price 0.07,0.007,0.28] [--out DIR]

Writes <out>/questions.csv (one row per record), calls.csv (one row per model call), executions.csv (one row per
program run) and stats.json; out defaults to the first run folder.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gen.teacher import Prices


def load(runs):
    for run in runs:
        for path in sorted(Path(run).glob('logs/*.json')):
            try:
                rec = json.loads(path.read_text(encoding='utf-8'))
            except ValueError:
                continue
            if rec.get('schema', '').startswith('teacher_record'):
                yield Path(run).name, path.name, rec


def tables(runs, prices):
    qs, calls, execs = [], [], []
    for run, file, r in load(runs):
        g, t = r.get('gold') or {}, r.get('totals') or {}
        key = {'run': run, 'file': file, 'id': r['id'], 'sample': r.get('sample', 0), 'business_id': r.get('business_id')}
        qs.append({**key, 'gold_type': g.get('type'), 'type': r.get('type'), 'outcome': r.get('outcome'),
                   'reason': r.get('reason'), 'calls': r.get('calls'), 'seconds': r.get('seconds'),
                   'question_chars': len(r.get('question') or ''), 'as_of': r.get('as_of'), 'model': r['input'].get('model'),
                   'temperature': r['input'].get('temperature'), 'seed': r['input'].get('seed'),
                   **{k: v for k, v in t.items() if not isinstance(v, list)},
                   'finishes': '|'.join(str(x) for x in t.get('finishes', [])),
                   'cost_usd': sum(prices.cost(c.get('usage')) or 0 for c in r.get('llm_calls', [])) if prices.on else t.get('cost_usd')})
        for c in r.get('llm_calls', []):
            m, tok = c.get('meta') or {}, c.get('tokens') or prices.tokens(c.get('usage'))
            calls.append({**key, 'call': c['index'], 'outcome': r.get('outcome'), 'finish': c.get('finish'), 'error': c.get('error'),
                          'seconds': c.get('seconds'), 'queue_s': m.get('queue_s'), 'first_reasoning_s': m.get('first_reasoning_s'),
                          'first_content_s': m.get('first_content_s'), 'attempts': m.get('attempts'),
                          'retried_errors': len(m.get('retried_errors') or []), 'response_model': m.get('model'),
                          'system_fingerprint': m.get('system_fingerprint'), 'n_messages': len(c.get('messages') or []),
                          'input_chars': sum(c.get('message_chars') or []), 'output_chars': c.get('output_chars'),
                          'reasoning_chars': c.get('reasoning_chars'), **{f'{k}_tokens': v for k, v in tok.items()},
                          'cost_usd': prices.cost(c.get('usage')) if prices.on else c.get('cost_usd')})
        for e in r.get('trace', []):
            if e.get('event') == 'execution':
                err = e.get('error') or {}
                execs.append({**key, 'turn': e.get('turn'), 'answer_type': e.get('answer_type'), 'ok': e.get('ok'),
                              'explore': bool(e.get('explore')), 'error_type': err.get('type'), 'seconds': e.get('seconds'),
                              'code_lines': (e.get('code') or '').count('\n') + 1, 'issues': len(e.get('issues') or [])})
    return pd.DataFrame(qs), pd.DataFrame(calls), pd.DataFrame(execs)


def pct(s, qs=(0.5, 0.9, 0.99)):
    s = pd.to_numeric(s, errors='coerce').dropna()
    return {f'p{int(q * 100)}': round(float(s.quantile(q)), 2) for q in qs} | {'mean': round(float(s.mean()), 2)} if len(s) else {}


def summary(q, c, x):
    graded = q[q.outcome.isin(['correct', 'wrong', 'abstain'])]
    count = lambda s: {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}
    by = lambda col: {str(k): {'n': len(g), 'correct': int((g.outcome == 'correct').sum()), 'wrong': int((g.outcome == 'wrong').sum()),
                               'abstain': int((g.outcome == 'abstain').sum())} for k, g in graded.groupby(col, dropna=False)}
    out = {'records': len(q), 'questions': int(q.id.nunique()) if len(q) else 0, 'outcomes': count(q.outcome) if len(q) else {},
           'pa': round(((graded.outcome == 'correct').sum() - (graded.outcome == 'wrong').sum()) / len(graded), 4) if len(graded) else None,
           'reasons': count(q.reason) if len(q) else {}, 'calls_per_question': count(q.calls) if len(q) else {},
           'by_gold_type': by('gold_type') if len(graded) else {}, 'by_business': by('business_id') if len(graded) else {},
           'seconds_question': pct(q.get('seconds', [])), 'cost_usd_total': round(float(pd.to_numeric(q.get('cost_usd'), errors='coerce').sum()), 6) if len(q) else 0}
    if len(c):
        out['llm'] = {'calls': len(c), 'errors': int(c.error.notna().sum()), 'finishes': count(c.finish),
                      'retried_errors': int(c.retried_errors.sum()), 'seconds': pct(c.seconds), 'first_content_s': pct(c.first_content_s),
                      'queue_s': pct(c.queue_s), 'response_models': count(c.response_model),
                      **{f'{k}_tokens': {'sum': int(c[f'{k}_tokens'].sum()), **pct(c[f'{k}_tokens'])}
                         for k in ('prompt', 'cache_hit', 'completion', 'reasoning')},
                      'cache_hit_rate': round(c.cache_hit_tokens.sum() / max(1, c.prompt_tokens.sum()), 4)}
    if len(x):
        out['executions'] = {'n': len(x), 'ok': int(x.ok.sum()), 'explore': int(x.explore.sum()), 'error_types': count(x.error_type[~x.ok]),
                             'seconds': pct(x.seconds)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--price', help='USD per 1M tokens: input_miss,input_hit,output (recomputes cost)')
    ap.add_argument('--out')
    a = ap.parse_args(argv)
    q, c, x = tables(a.runs, Prices(a.price))
    out = Path(a.out or a.runs[0])
    out.mkdir(parents=True, exist_ok=True)
    for name, df in (('questions', q), ('calls', c), ('executions', x)):
        df.to_csv(out / f'{name}.csv', index=False)
    s = summary(q, c, x)
    (out / 'stats.json').write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(s, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
