from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

BASE_MODEL = {
    "name": "google/gemma-4-12B-it",
    "url": "https://huggingface.co/google/gemma-4-12B-it",
    "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
    "revision_date": "2026-07-20",
    "created": "2026-05-23",
    "license": "apache-2.0",
    "parameters": 11959730224,
    "files_sha256": {
        "model.safetensors": "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d",
        "tokenizer.json": "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
    },
    "local_path": "models/gemma-4-12B-it",
}
SKIPPED_NAMES = frozenset({".DS_Store"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(root: Path, base: Path) -> list[dict[str, object]]:
    if not root.exists():
        return []
    return [{"path": str(path.relative_to(base)), "bytes": path.stat().st_size, "sha256": _sha256(path)} for path in sorted(root.rglob("*")) if path.is_file() and path.name not in SKIPPED_NAMES]


def _lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.exists() else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ghi data_manifest.json: đường dẫn, kích thước, SHA-256 của dữ liệu, thư viện ví dụ và weights")
    parser.add_argument("--code", type=Path, required=True, help="thư mục gốc của solution (chứa src/, models/, training_code/)")
    args = parser.parse_args(argv)
    code = args.code.resolve()
    data = code / "training_code" / "data"
    prompts = code / "src" / "datamate_agent" / "prompts"
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training": "none: no model weights were trained or fine-tuned; the only generated data is the few-shot example library",
        "base_model": BASE_MODEL,
        "datasets": [
            {"name": "provided train set", "path": "training_code/data/train", "questions": _lines(data / "train" / "questions.jsonl"), "split": {"train_questions": _lines(data / "train" / "split" / "train_questions.jsonl"), "test_questions": _lines(data / "train" / "split" / "test_questions.jsonl")}},
            {"name": "agent-written examples matching train gold", "path": "training_code/data/library_agent.jsonl", "examples": _lines(data / "library_agent.jsonl"), "evidence": "training_code/data/agent_example_logs (prompt and response of each source run)"},
        ],
        "outputs": [
            {"path": "src/datamate_agent/prompts/library.jsonl", "examples": _lines(prompts / "library.jsonl"), "sha256": _sha256(prompts / "library.jsonl"), "built_by": "training_code/data_generation/build_library.py"},
            {"path": "src/datamate_agent/prompts/library_curated.jsonl", "examples": _lines(prompts / "library_curated.jsonl"), "sha256": _sha256(prompts / "library_curated.jsonl"), "built_by": "hand-written"},
        ],
        "files": _files(data, code) + _files(code / "models", code),
    }
    target = code / "training_code" / "data_manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{target}: {len(manifest['files'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
