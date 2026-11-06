from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Protocol

from ..models import ExecResult, ExecutorConfig
from .paths import DATA_VISIBLE

CONTAINER_ROOT = "/sandbox"
CONTAINER_DATA = f"{CONTAINER_ROOT}/data"
CONTAINER_WORK = f"{CONTAINER_ROOT}/work"
CONTAINER_SRC = "/app/src"


class Executor(Protocol):
    """Chạy một script Python nằm trong `work/` với đúng ba biến môi trường của toolkit."""

    def run(self, script: Path) -> ExecResult: ...


class LocalExecutor:
    """Chạy bằng subprocess trên máy, cwd có sẵn `data/` và `work/` như tool; không cô lập file, mạng hay gold (ADR 005)."""

    def __init__(self, config: ExecutorConfig, *, data_root: Path, work_root: Path, src_root: Path) -> None:
        self._config = config
        self._sandbox = Path(tempfile.mkdtemp(prefix="datamate-sandbox-"))
        (self._sandbox / "data").mkdir()
        for name in DATA_VISIBLE:
            (self._sandbox / "data" / name).symlink_to((data_root / name).resolve())
        (self._sandbox / "work").symlink_to(work_root.resolve())
        self._env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(work_root),
            "PYTHONPATH": str(src_root),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "DATAMATE_DATA": str(self._sandbox / "data"),
            "DATAMATE_WORK": str(self._sandbox / "work"),
            "DATAMATE_CALENDAR": str(self._sandbox / "data" / "calendar.csv"),
        }

    def run(self, script: Path) -> ExecResult:
        return _run_process([sys.executable, str(script)], cwd=self._sandbox, env=self._env, timeout_s=self._config.timeout_s, on_timeout=None)


class DockerExecutor:
    """Chạy trong container không mạng, cwd `/sandbox` có `data/` (chỉ DATA_VISIBLE, chỉ đọc) và `work/` (đọc ghi)."""

    def __init__(self, config: ExecutorConfig, *, data_root: Path, work_root: Path, src_root: Path) -> None:
        if config.docker_image is None:
            raise ValueError("docker executor needs docker_image")
        self._config = config
        self._data_root = data_root
        self._work_root = work_root
        self._src_root = src_root

    def run(self, script: Path) -> ExecResult:
        inside = f"{CONTAINER_WORK}/{script.resolve().relative_to(self._work_root.resolve()).as_posix()}"
        name = f"datamate-{uuid.uuid4().hex[:12]}"
        command = [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",
            "--memory", self._config.docker_memory,
            "--cpus", str(self._config.docker_cpus),
            "--user", f"{os.getuid()}:{os.getgid()}",
            *_visible_data_mounts(self._data_root),
            "-v", f"{self._work_root}:{CONTAINER_WORK}",
            "-v", f"{self._src_root}:{CONTAINER_SRC}:ro",
            "-w", CONTAINER_ROOT,
            "-e", f"PYTHONPATH={CONTAINER_SRC}",
            "-e", "PYTHONIOENCODING=utf-8",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", f"HOME={CONTAINER_WORK}",
            "-e", f"DATAMATE_DATA={CONTAINER_DATA}",
            "-e", f"DATAMATE_WORK={CONTAINER_WORK}",
            "-e", f"DATAMATE_CALENDAR={CONTAINER_DATA}/calendar.csv",
            self._config.docker_image,
            "python", inside,
        ]
        return _run_process(command, cwd=self._work_root, env=None, timeout_s=self._config.timeout_s, on_timeout=("docker", "kill", name))


def _visible_data_mounts(data_root: Path) -> list[str]:
    mounts: list[str] = []
    for name in DATA_VISIBLE:
        source = data_root / name
        if not source.exists():
            raise ValueError(f"dataset is missing {name}: {source}")
        mounts += ["-v", f"{source.resolve()}:{CONTAINER_DATA}/{name}:ro"]
    return mounts


def build_executor(config: ExecutorConfig, *, data_root: Path, work_root: Path, src_root: Path) -> Executor:
    if config.kind == "docker":
        return DockerExecutor(config, data_root=data_root, work_root=work_root, src_root=src_root)
    return LocalExecutor(config, data_root=data_root, work_root=work_root, src_root=src_root)


def _run_process(command: list[str], *, cwd: Path, env: dict[str, str] | None, timeout_s: int, on_timeout: tuple[str, ...] | None) -> ExecResult:
    started = time.monotonic()
    try:
        done = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as expired:
        if on_timeout is not None:
            subprocess.run(list(on_timeout), capture_output=True, text=True)
        return ExecResult(
            exit_code=None,
            stdout=_text(expired.stdout),
            stderr=_text(expired.stderr) + f"\ntimed out after {timeout_s}s",
            timed_out=True,
            duration_s=round(time.monotonic() - started, 3),
        )
    return ExecResult(
        exit_code=done.returncode,
        stdout=done.stdout,
        stderr=done.stderr,
        timed_out=False,
        duration_s=round(time.monotonic() - started, 3),
    )


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
