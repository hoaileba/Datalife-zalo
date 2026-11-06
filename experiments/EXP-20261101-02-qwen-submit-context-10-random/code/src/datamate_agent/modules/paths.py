from __future__ import annotations

from pathlib import Path

DATA_ROOT = "data"
WORK_ROOT = "work"
DATA_VISIBLE = ("rulebook.md", "calendar.csv", "data")


class PathSpace:
    """Hai gốc ảo model nhìn thấy: `data/` chỉ đọc và chỉ lộ DATA_VISIBLE, `work/` đọc ghi."""

    def __init__(self, *, data_root: Path, work_root: Path) -> None:
        self._roots = {DATA_ROOT: data_root.resolve(), WORK_ROOT: work_root.resolve()}

    @property
    def data_root(self) -> Path:
        return self._roots[DATA_ROOT]

    @property
    def work_root(self) -> Path:
        return self._roots[WORK_ROOT]

    def resolve(self, virtual: str, *, write: bool) -> Path:
        cleaned = virtual.strip().replace("\\", "/").lstrip("./")
        head, _, rest = cleaned.partition("/")
        if head not in self._roots:
            raise ValueError(f"path must start with data/ or work/: {virtual!r}")
        if write and head == DATA_ROOT:
            raise ValueError(f"data/ is read-only: {virtual!r}")
        root = self._roots[head]
        target = (root / rest).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"path escapes {head}/: {virtual!r}")
        if not self.is_visible(target):
            raise ValueError(f"not visible to the agent: {virtual!r}")
        return target

    def is_visible(self, real: Path) -> bool:
        resolved = real.resolve()
        data = self._roots[DATA_ROOT]
        if resolved == data or data not in resolved.parents:
            return True
        return resolved.relative_to(data).parts[0] in DATA_VISIBLE

    def virtual(self, real: Path) -> str:
        resolved = real.resolve()
        for name, root in self._roots.items():
            if resolved == root:
                return name
            if root in resolved.parents:
                return f"{name}/{resolved.relative_to(root).as_posix()}"
        raise ValueError(f"path outside data/ and work/: {real}")


class WorkLayout:
    """Bố cục `output_dir` của một lần chạy, cùng dạng thư mục thực nghiệm trong AGENT.md."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def script(self, shop: str) -> Path:
        return self.root / "code" / "shops" / f"{shop}.py"

    def answers(self, shop: str) -> Path:
        return self.root / "out" / "answers" / f"{shop}.jsonl"

    def answers_dir(self) -> Path:
        return self.root / "out" / "answers"

    def questions(self, shop: str) -> Path:
        return self.root / "inputs" / f"{shop}-questions.jsonl"

    def scratch(self, shop: str) -> Path:
        return self.root / "scratch" / shop

    def submission(self) -> Path:
        return self.root / "out" / "submission.jsonl"

    def score(self) -> Path:
        return self.root / "out" / "score.json"

    def run_logs(self) -> Path:
        return self.root / "logs" / "runs"

    def combined_log(self) -> Path:
        return self.root / "logs" / "run.log"

    def combined_tools_log(self) -> Path:
        return self.root / "logs" / "tools.log"

    def state(self) -> Path:
        return self.root / "state.json"
