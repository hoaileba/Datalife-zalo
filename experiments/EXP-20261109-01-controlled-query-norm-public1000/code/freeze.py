from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
INPUTS = EXPERIMENT / "code/inputs"


def sha(path: Path) -> str:
    state = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            state.update(block)
    return state.hexdigest()


def main() -> int:
    snapshot = EXPERIMENT / "code/src"
    if snapshot.exists() or INPUTS.exists():
        raise ValueError("snapshot already exists; do not overwrite a frozen experiment")
    shutil.copytree(ROOT / "src", snapshot, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    INPUTS.mkdir()
    for source, name in (
        (ROOT / "public_test/questions.jsonl", "questions.jsonl"),
        (ROOT / "experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl", "reference.jsonl"),
        (ROOT / "experiments/EXP-20261108-02-gemma4-public1000/out/submission.jsonl", "baseline_submission.jsonl"),
        (ROOT / "experiments/EXP-20261108-02-gemma4-public1000/out/analysis_public.jsonl", "baseline_analysis.jsonl"),
        (ROOT / "public_test/calendar.csv", "calendar.csv"),
        (ROOT / "public_test/rulebook.md", "rulebook.md"),
        (ROOT / "AGENT.md", "AGENT.md"),
    ):
        shutil.copyfile(source, INPUTS / name)
    shutil.copytree(ROOT / "artifacts/norm/public_test", INPUTS / "norm/public_test")
    scorer = (ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8")
    (INPUTS / "score_source.py").write_text(scorer, encoding="utf-8")
    prefix = scorer.split("Q, G = load(", 1)[0].replace('glob.glob(f"artifacts/norm/public_test/{shop}/*.csv")', 'glob.glob(str(NORM_PATH / shop / "*.csv"))')
    (INPUTS / "score_prefix.py").write_text(prefix, encoding="utf-8")
    files = sorted(path for folder in (snapshot, INPUTS) for path in folder.rglob("*") if path.is_file())
    hashes = {path.relative_to(EXPERIMENT).as_posix(): sha(path) for path in files}
    (EXPERIMENT / "code/snapshot_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_and_input_files": len(hashes), "bytes": sum(path.stat().st_size for path in files), "snapshot_has_symlinks": any(path.is_symlink() for folder in (snapshot, INPUTS) for path in folder.rglob("*"))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
