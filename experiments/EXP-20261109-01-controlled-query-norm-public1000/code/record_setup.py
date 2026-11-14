from __future__ import annotations

import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]


def main() -> int:
    prefix = FOLDER.relative_to(FOLDER.parents[1]).as_posix()
    commands = {
        "01-synthetic-tests": f"PYTHONPATH=src python3 {prefix}/code/test_normalization.py > {prefix}/logs/01-synthetic-tests.log 2>&1",
        "02-synthetic-tests": f"PYTHONPATH=src python3 {prefix}/code/test_normalization.py > {prefix}/logs/02-synthetic-tests.log 2>&1",
        "03-freeze": f"python3 {prefix}/code/freeze.py > {prefix}/logs/03-freeze.log 2>&1",
        "04-snapshot-tests": f"PYTHONPATH={prefix}/code/src python3 {prefix}/code/test_normalization.py > {prefix}/logs/04-snapshot-tests.log 2>&1",
    }
    for name, stage in (("05-server-check", "check"), ("06-server-check-escalated", "check"), ("07-smoke", "smoke"), ("08-full", "full")):
        commands[name] = f"python3 {prefix}/code/runner.py {stage} > {prefix}/logs/{name}.log 2>&1"
    for name, command in commands.items():
        target = FOLDER / "logs" / f"{name}.cmd"
        if not target.exists():
            target.write_text(command + "\n", encoding="utf-8")
    versions = {name: importlib.metadata.version(name) for name in ("openai", "httpx", "pydantic", "pandas", "openpyxl")}
    (FOLDER / "code/package_versions.json").write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
    with (FOLDER / "STEPS.md").open("a", encoding="utf-8") as sink:
        sink.write(f"\n## {datetime.now(timezone.utc).isoformat()} — bước 2/7\nĐã làm: thêm question_normalize, CLI opt-in/cache riêng; kiểm synthetic và freeze source/input.\nKết quả: log01 có một assertion message thất bại dù ID bị chặn; log02/log04 có15 pass. Snapshot210 file, không symlink. Model inventory qua network được cấp quyền trả gemma-12b; URL/key chỉ ở env process.\nBước tiếp: smoke không chấm gold, sau đó full1000 mới từ snapshot.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
