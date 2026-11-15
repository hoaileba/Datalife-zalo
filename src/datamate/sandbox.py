"""Run agent code in a child Python process with hard limits. Works in any Docker image: plain subprocess,
resource.setrlimit and a timeout; no bubblewrap, namespaces or seccomp.

In:  code, the pickled business path, as_of.  Out: `Execution` (ok, result, stdout, error dict).
Limits: address space (memory), CPU seconds, file size (no large writes), wall-clock timeout; private temp cwd,
minimal environment. Network is disabled by the competition's Docker run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .worker import MARKER

SRC = str(Path(__file__).resolve().parent.parent)


@dataclass
class Limits:
    memory_bytes: int = 4 << 30
    cpu_seconds: int = 60
    wall_seconds: float = 30.0
    file_bytes: int = 16 << 20
    max_stdout: int = 20000


@dataclass
class Execution:
    ok: bool
    result: object = None
    stdout: str = ''
    error: dict = field(default_factory=dict)        # type, message, line, source
    trace: str = ''                                   # the shape of each top-level assignment (program.add_trace)

    def error_text(self):
        e = self.error
        where = f" (line {e['line']}: {e['source']})" if e.get('line') else ''
        values = f" | Variables on that line: {e['values']}" if e.get('values') else ''
        hint = f" | {e['hint']}" if e.get('hint') else ''                 # last: a long table list never hides the line
        return f"{e.get('type')}: {e.get('message')}{where}{values}{hint}"


def execute(code: str, tables_path: Path, as_of: str, limits: Limits | None = None, typed: bool = True) -> Execution:
    """typed: result must be the agent's {"type", "answer"} dict (shape.typed); False: any value (replay of old programs)."""
    limits = limits or Limits()
    request = json.dumps({'code': code, 'typed': typed, 'tables_path': str(Path(tables_path).resolve()), 'as_of': str(as_of), 'max_stdout': limits.max_stdout,
                          'limits': [limits.memory_bytes, limits.cpu_seconds, limits.file_bytes]})
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': SRC, 'PYTHONIOENCODING': 'utf-8',
           'PYTHONHASHSEED': '0', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    with tempfile.TemporaryDirectory(prefix='dm4-run-') as cwd:
        env['HOME'] = env['TMPDIR'] = cwd
        if os.name == 'nt':                         # Windows dev: Python needs SYSTEMROOT, temp dirs read TEMP/TMP
            env.update(SYSTEMROOT=os.environ.get('SYSTEMROOT', 'C:\\Windows'), TEMP=cwd, TMP=cwd)
        proc = subprocess.Popen([sys.executable, '-m', 'datamate.worker'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd, env=env, start_new_session=True)   # limits: worker.main
        try:
            out, err = proc.communicate(request.encode(), timeout=limits.wall_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, 9) if hasattr(os, "killpg") else proc.kill()   # Windows dev: no process groups
            except ProcessLookupError:
                pass
            proc.communicate()
            return Execution(False, error={'type': 'Timeout', 'message': f'the program ran longer than {limits.wall_seconds:.0f} s: '
                                                                         'use vectorized pandas, no loops over rows'})
    text = out.decode('utf-8', errors='replace')
    if MARKER not in text:
        tail = err.decode('utf-8', errors='replace')[-800:]
        if proc.returncode == -24:                    # SIGXCPU
            return Execution(False, error={'type': 'Timeout', 'message': f'the program used more than {limits.cpu_seconds} s '
                                                                         'of CPU: use vectorized pandas, no loops over rows'})
        kind = 'MemoryLimit' if proc.returncode in (-9, 137) or 'MemoryError' in tail else 'Crash'
        return Execution(False, error={'type': kind, 'message': f'worker exited with code {proc.returncode}: {tail}'})
    response = json.loads(text.rsplit(MARKER, 1)[1])
    return Execution(response['ok'], response.get('result'), response.get('stdout', ''), response.get('error') or {}, response.get('trace', ''))
