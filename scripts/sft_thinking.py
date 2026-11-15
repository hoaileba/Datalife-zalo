"""Add the teacher's raw thinking to every sample of a gen.package folder (student then runs with thinking ON).

Each sample's completion message gets `reasoning` = the thinking DeepSeek produced in the call that wrote that turn
(teacher log `llm_calls[turn].reasoning`). That is the key the Gemma 4 chat template reads: it renders an assistant
message as `<|channel>thought\\n{reasoning}\\n<channel|>{content}`, and drops the thinking of earlier turns (so the
prompt messages stay as they are). train/sft_lora.py renders such a sample with enable_thinking=True.

Checks: the turn's call output must contain the completion (last code line, or the first line of a decision);
samples without thinking or longer than --max-len are dropped (record-level: all samples of that teacher record).
Token counts are exact when `tokenizers` is importable (Gemma 4 tokenizer.json), estimated (chars / 3) otherwise.

No model calls.
  python scripts/sft_thinking.py --package outputs/sft/_v3_base --out outputs/sft/train_v3 [--max-len 28672]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENIZER = ROOT / 'outputs' / 'tokenizers' / 'gemma-4-12B-it' / 'tokenizer.json'
OPEN, CLOSE = '<|channel>thought\n', '\n<channel|>'
CODE = re.compile(r'```python\n(.*?)```', re.S)


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def counter():
    try:
        from tokenizers import Tokenizer
        tk = Tokenizer.from_file(str(TOKENIZER))
        return (lambda texts: [len(e.ids) for e in tk.encode_batch(texts, add_special_tokens=False)]), True
    except Exception:                                   # noqa: BLE001
        return (lambda texts: [len(t) // 3 + 1 for t in texts]), False


def anchor(content):
    """A line of the completion that must appear in the teacher's raw output of the same call."""
    m = CODE.search(content)
    lines = (m.group(1) if m else content).strip().splitlines()
    return (lines[-1] if m else lines[0]).strip() if lines else ''


def quantiles(xs):
    xs = sorted(xs)
    if not xs:
        return {}
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
    return {'n': len(xs), 'min': xs[0], 'p50': q(.5), 'p90': q(.9), 'p99': q(.99), 'max': xs[-1],
            'mean': round(sum(xs) / len(xs), 1), 'sum': sum(xs)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--package', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-len', type=int, default=28672, help='drop records with a sample longer than this (tokens)')
    a = ap.parse_args()
    pkg, out = Path(a.package), Path(a.out)
    count, exact = counter()
    out.mkdir(parents=True, exist_ok=True)
    report = {'package': str(pkg), 'max_len': a.max_len, 'tokens_exact': exact, 'dropped_records': {}, 'samples': {}}
    lengths = {}
    for side in ('train', 'val'):
        if not (pkg / f'{side}.jsonl').exists():
            continue
        rows, metas = read_jsonl(pkg / f'{side}.jsonl'), read_jsonl(pkg / f'{side}_meta.jsonl')
        if len(rows) != len(metas) or any(r['id'] != m['key'] for r, m in zip(rows, metas)):
            raise SystemExit(f'{side}.jsonl and {side}_meta.jsonl disagree')
        logs, thoughts, why = {}, [], {}
        for r, m in zip(rows, metas):
            path = ROOT / m['run_path'] / m['record']
            if path not in logs:
                logs = {path: json.loads(path.read_text(encoding='utf-8'))}     # metas are grouped by record
            calls = logs[path].get('llm_calls') or []
            call = calls[m['turn']] if m['turn'] < len(calls) else {}
            text = (call.get('reasoning') or '').strip()
            key = (m['run'], m['id'])
            if not text:
                why.setdefault(key, 'no_thinking')
            elif anchor(r['completion'][0]['content']) not in (call.get('output') or ''):
                why.setdefault(key, 'turn_mismatch')
            thoughts.append(text)
        ntok = count([OPEN + t + CLOSE for t in thoughts])
        for m, n in zip(metas, ntok):
            # prompt rendered with enable_thinking: +<|think|>\n in the system turn, no empty thought channel (~+-3)
            if m['total_tokens'] + n > a.max_len:
                why.setdefault((m['run'], m['id']), 'too_long')
        keep_rows, keep_metas = [], []
        for r, m, t, n in zip(rows, metas, thoughts, ntok):
            if (m['run'], m['id']) in why:
                continue
            r['completion'][0]['reasoning'] = t
            m.update(thinking='teacher_raw', thinking_chars=len(t), thinking_tokens=n,
                     completion_tokens=m['completion_tokens'] + n, total_tokens=m['total_tokens'] + n)
            keep_rows.append(r)
            keep_metas.append(m)
        write_jsonl(out / f'{side}.jsonl', keep_rows)
        write_jsonl(out / f'{side}_meta.jsonl', keep_metas)
        c = collections.Counter(why.values())
        report['dropped_records'][side] = dict(c)
        report['samples'][side] = len(keep_rows)
        report['samples'][f'{side}_final'] = sum(1 for m in keep_metas if m.get('final'))
        lengths[side] = {k: quantiles([m[k] for m in keep_metas])
                         for k in ('prompt_tokens', 'thinking_tokens', 'completion_tokens', 'total_tokens')}
        print(side, len(keep_rows), 'samples kept; dropped records', dict(c), flush=True)

    for f in pkg.iterdir():                               # README, val_questions, stats ...
        if f.is_file() and not re.fullmatch(r'(train|val)(_meta)?\.jsonl', f.name) and f.name != 'filtered.json':
            shutil.copy2(f, out / f.name)
    shutil.copy2(ROOT / 'train' / 'sft_lora.py', out / 'sft_lora.py')
    if (pkg / 'filtered.json').exists():
        shutil.copy2(pkg / 'filtered.json', out / 'filtered.json')
    (out / 'thinking.json').write_text(json.dumps({**report, 'lengths': lengths}, ensure_ascii=False, indent=1), encoding='utf-8')

    # stats.json: counts, lengths and distributions of THIS package (not the parent's), file hashes
    stats = json.loads((out / 'stats.json').read_text(encoding='utf-8'))
    stats['samples'] = {**stats.get('samples', {}), **report['samples']}
    stats['lengths'] = lengths
    stats['max_total_tokens'] = max(v['total_tokens']['max'] for v in lengths.values())
    stats['options'] = {**stats.get('options', {}), 'max_len': a.max_len, 'thinking': 'teacher_raw'}
    dist = {}
    for side in lengths:
        metas = read_jsonl(out / f'{side}_meta.jsonl')
        dist[side] = {k: dict(collections.Counter(str(m.get(k)) for m in metas).most_common())
                      for k in ('gold_type', 'answer_type', 'final', 'turn', 'run', 'business_id', 'industry', 'intent')}
        dist[side]['questions'] = len({m['group'] for m in metas})
    stats['distributions'] = dist
    stats.setdefault('derived', []).append({'by': 'scripts/sft_thinking.py', 'from': str(pkg),
                                            'dropped_records': report['dropped_records']})
    stats['files'] = {f.name: {'bytes': f.stat().st_size, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
                      for f in sorted(out.iterdir()) if f.is_file() and f.name != 'stats.json'}
    (out / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'samples': report['samples'], 'tokens_exact': exact,
                      'total_tokens': {s: lengths[s]['total_tokens'] for s in lengths}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
