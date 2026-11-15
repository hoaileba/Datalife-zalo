"""Hand-off folder in the Docker guideline layout (docs/zac/docker_guideline.pdf §4, §8): /code/training_code/.

  <out>/data/               train.jsonl, val.jsonl (+ *_meta.jsonl, stats.json) of the final package; core/ subset;
                            think/ variant (REASON as thinking, scripts/reason_as_thinking.py) when given
  <out>/data_generation/    gen/, scripts used, the frozen agent src/ (prompts are rebuilt with it), configs
  <out>/configs/            teacher configs, teacher note, system prompt, run script
  <out>/logs/teacher/       every teacher record (exact prompts and responses of the API calls), gzip per run
  <out>/data_manifest.json  every file: path, bytes, SHA-256; dataset counts/splits; generator model/settings; git commit
  <out>/README.md           what was done, exact commands, counts (filled from stats)

No model calls.  python scripts/export_training_code.py --package outputs/sft/final --core outputs/sft/final_core \
    --think outputs/sft/final_think --teacher-root outputs/teacher/final --out outputs/training_code
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ['gen', 'scripts/select_train_a.py', 'scripts/run_final_data.sh', 'scripts/reason_as_thinking.py',
        'scripts/export_training_code.py', 'scripts/train_intents.py', 'scripts/run_more_data.sh', 'scripts/select_train_gap.py', 'scripts/run_gap_data.sh', 'scripts/review_chunk.py', 'scripts/run_b9.sh', 'scripts/postfilter.py', 'scripts/augment_dates.py', 'scripts/check_code_style.py', 'src', 'train']
CONFIGS = ['config.yaml', 'config.final_nothink.yaml', 'config.deepseek_direct.yaml', 'gen/assets/teacher_note.md',
           'src/datamate/assets/prompt.md']


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def copy(src, dst):
    src, dst = Path(src), Path(dst)
    if src.is_dir():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.tmp'))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def count(path):
    return sum(1 for line in open(path, encoding='utf-8') if line.strip()) if path.exists() else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', required=True)
    ap.add_argument('--core')
    ap.add_argument('--think')
    ap.add_argument('--teacher-root', required=True, nargs='+')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    copy(a.package, out / 'data')
    if a.core:
        copy(a.core, out / 'data' / 'core')
    if a.think:
        copy(a.think, out / 'data' / 'think')
    for c in CODE:
        copy(ROOT / c, out / 'data_generation' / c)
    for c in CONFIGS:
        copy(ROOT / c, out / 'configs' / Path(c).name)
    copy(ROOT / 'docs' / 'TRAINING_CODE_README.md', out / 'README.md')
    logs = out / 'logs' / 'teacher'
    logs.mkdir(parents=True)
    runs = sorted(p for root in a.teacher_root for p in Path(root).iterdir() if (p / 'logs').is_dir())
    for run in runs:                                    # exact prompts/responses of every API call, one archive per run
        with tarfile.open(logs / f'{run.name}.tar.gz', 'w:gz') as tf:
            for name in ('logs', 'run.json', 'summary.json', 'config.yaml', 'system_prompt.md', 'index.jsonl'):
                if (run / name).exists():
                    tf.add(run / name, arcname=f'{run.name}/{name}')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    stats = json.loads((Path(a.package) / 'stats.json').read_text(encoding='utf-8'))
    manifest = {
        'git_commit': commit,
        'base_model': {'name': 'google/gemma-4-12B-it', 'note': 'public base model; see /code/README.md for revision and license'},
        'generator': {'model': 'DeepSeek V4.1 flash (deepseek-flash) via api.deepseek.com',
                      'pass1': 'thinking disabled, temperature 0, seed 0, max_tokens 8192 (configs/config.final_nothink.yaml)',
                      'pass2': 'thinking enabled on pass-1 misses, max_tokens 32768 (configs/config.deepseek_direct.yaml)',
                      'teacher_note': 'configs/teacher_note.md appended to the teacher system prompt only; student prompts '
                                      'are rebuilt with the agent code (data_generation/src)'},
        'datasets': {
            'train': count(out / 'data' / 'train.jsonl'), 'val': count(out / 'data' / 'val.jsonl'),
            'core_train': count(out / 'data' / 'core' / 'train.jsonl'), 'think_train': count(out / 'data' / 'think' / 'train.jsonl'),
            'sources': 'A: train questions of data/train (27 shops; held-out biz_108/110/130 in val); B9: moved-rule worlds; forced: fix turns after code-written first turns (gen/forced.py); R1/R2, G1/G2: train '
                       'questions re-solved on reskinned tables (data_gen/reskin_1, reskin_2); B0-B8: self-generated unique '
                       'worlds (gen/world.py); CW/CS: val (held-out generated trades, held-out shops). No public/private test data.',
            'postfilter': 'data/POSTFILTER.json'},
        'package_stats': {k: stats.get(k) for k in ('samples', 'records', 'dropped_records', 'dropped_samples', 'tokens')},
        'files': [],
    }
    for p in sorted(out.rglob('*')):
        if p.is_file() and p.name != 'data_manifest.json':
            manifest['files'].append({'path': p.relative_to(out).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)})
    (out / 'data_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: manifest[k] for k in ('git_commit', 'datasets')}, ensure_ascii=False, indent=1))
    print(f"{len(manifest['files'])} files, {sum(f['bytes'] for f in manifest['files']) / 1e6:.0f} MB -> {out}")


if __name__ == '__main__':
    main()
