"""Sandbox child process: run one agent program against one business's tables (python -m datamate.worker).

In (stdin JSON):  {'code', 'tables_path' (pickled Business), 'as_of' 'YYYY-MM-DD', 'max_stdout'}.
Out (last stdout line, after MARKER): {'ok': true, 'result': <shape.shape value>, 'stdout'} or
     {'ok': false, 'error': {'type', 'message', 'line', 'source', 'values'}, 'stdout'}; values = type and short value
     of each variable the failing line reads.
Limits (memory, CPU, file size) are set by the parent (sandbox.py) before exec; this module only runs the code.
"""
from __future__ import annotations

import io
import json
import re
import sys

MARKER = '\x1e@@DATAMATE_RESULT@@'
NO_RESULT = ('The program ran but never assigned result: the last line must be result = <value to submit>')


class _Capture(io.StringIO):
    def __init__(self, limit):
        super().__init__(); self.limit = limit
    def write(self, s):
        if self.tell() < self.limit:
            super().write(s[: self.limit - self.tell()])
        return len(s)


def _namespace(business, as_of):
    import datetime
    import math
    import types
    from collections.abc import Mapping
    from decimal import Decimal, ROUND_HALF_UP
    import numpy as np
    import pandas as pd
    from . import helpers

    class Tables(Mapping):
        def __init__(self): self.loaded = {}
        def __iter__(self): return iter(business.tables)
        def __len__(self): return len(business.tables)
        def __getitem__(self, name):
            if name not in business.tables:
                raise KeyError(f'Unknown table {name!r}. Tables: {list(business.tables)}')
            if name not in self.loaded:
                self.loaded[name] = helpers.TolerantFrame(business.tables[name])
            return self.loaded[name]

    def exact(x):
        """Decimal of a number as written: 2.675 stays 2.675 (shortest repr), so half-up rounding is exact."""
        if isinstance(x, Decimal):
            return x
        if isinstance(x, (bool, np.bool_)) or not isinstance(x, (int, float, np.integer, np.floating)):
            raise TypeError(f'round_decimal needs a number, got {type(x).__name__}')
        return Decimal(int(x)) if isinstance(x, (int, np.integer)) else Decimal(repr(float(x)))

    def round_decimal(value, places=0):
        one = lambda x: exact(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        return value.map(one) if isinstance(value, pd.Series) else one(value)

    def round_half_up(value, places=0):
        return float(round_decimal(value, places))

    dm = types.SimpleNamespace(**{n: getattr(helpers, n) for n in helpers.__all__})
    module = types.ModuleType('dm'); module.__dict__.update(vars(dm)); module.dm = dm
    sys.modules['dm'] = module                       # `import dm` / `from dm import ...` resolve to the helpers
    ns = {'__name__': '__agent__', 'pd': pd, 'np': np, 'dm': dm, 'datetime': datetime, 'math': math,
          'Decimal': Decimal, 'as_of': pd.Timestamp(as_of), 'tables': Tables(),
          'round_decimal': round_decimal, 'round_half_up': round_half_up, 'readme': getattr(business, 'readme', '') or ''}
    for name in business.tables:                     # don_hang IS tables['don_hang'] (models write both)
        if name.isidentifier() and name not in ns:
            ns[name] = ns['tables'][name]
    return ns


def _key_error_hint(exc, tables):
    """Say which loaded table has the missing column, and list the loaded tables' columns."""
    from .helpers import norm
    quoted = re.search(r"'([^']+)'", str(exc.args[0])) if exc.args else None
    key = norm(quoted.group(1) if quoted else str(exc.args[0] if exc.args else ''))
    owners = [n for n, f in tables.loaded.items() if any(norm(c) == key for c in f.columns)]
    cols = lambda f: [str(c) for c in f.columns if not str(c).endswith('__raw') and f[c].notna().any()]
    return (f'Found in table(s): {owners}. ' if owners else '') + 'Tables: ' + '; '.join(f'{n}: {cols(f)}' for n, f in tables.loaded.items())


HIDDEN = {'pd', 'np', 'dm', 'datetime', 'math', 'Decimal', 'tables', 'round_decimal', 'round_half_up', '__builtins__', '__name__', '__trace__', 'readme'}


def _describe(v):
    """Short type and value of one variable, so an error can be diagnosed without guessing."""
    kind = 'table' if hasattr(v, 'columns') else type(v).__name__
    if hasattr(v, 'columns') and hasattr(v, 'shape'):
        return f'{kind} {v.shape[0]} rows, columns {[str(c) for c in v.columns if not str(c).endswith("__raw")][:12]}'
    if hasattr(v, 'dtype') and hasattr(v, 'shape') and getattr(v, 'ndim', 0) == 1:
        return f'{kind} len {len(v)}, dtype {v.dtype}, first {[str(x) for x in list(v[:3])]}'
    if isinstance(v, (tuple, list, set, dict)):
        return f'{kind} of {len(v)}: {repr(v)[:160]}'
    text = repr(v)[:120]
    return text if text.startswith(kind) else f'{kind} {text}'


def _line_values(source, ns):
    """'name: type value' for the variables the failing line reads (at most 8), or ''."""
    import ast
    try:
        names = [n.id for n in ast.walk(ast.parse(source.strip().rstrip(':'))) if isinstance(n, ast.Name)]
    except SyntaxError:
        return ''
    seen = [n for n in dict.fromkeys(names) if n in ns and n not in HIDDEN][:8]
    return '; '.join(f'{n}: {_describe(ns[n])}' for n in seen)[:1200]


def run(request):
    import pickle
    from .program import error_location, tolerant_compile
    from .shape import ShapeError, shape
    out = _Capture(request.get('max_stdout', 20000))
    with open(request['tables_path'], 'rb') as f:
        business = pickle.load(f)
    ns = _namespace(business, request['as_of'])
    tables, code = ns['tables'], request['code']      # the program may rebind `tables`: hints use the host's own
    run.trace, seen = (trail := []), {}
    def brief(v):                                     # a table: its rows; its columns only when they changed (no __raw)
        if not (hasattr(v, 'columns') and hasattr(v, 'shape')):
            return _describe(v)
        cols = [str(c) for c in v.columns if not str(c).endswith('__raw')]
        same, seen['cols'] = seen.get('cols') == cols, cols
        return f'table {v.shape[0]} rows' + ('' if same else f', columns {cols[:20]}')
    def trace(line, names):                           # program.add_trace: the state after each top-level assignment
        try:
            trail.extend(f'line {line} {name}: {brief(ns[name])}'[:300] for name in names if name in ns)
        except Exception:                             # noqa: BLE001 - never sinks the program
            pass
        del trail[:-60]
    ns['__trace__'] = trace
    real_stdout, sys.stdout, sys.stderr = sys.stdout, out, out
    try:
        program, notes = tolerant_compile(code)
        for note in notes:
            print(note)
        exec(program, ns, ns)
        if 'result' not in ns:
            return {'ok': False, 'error': {'type': 'NoResult', 'message': NO_RESULT, 'line': None, 'source': None}}
        return {'ok': True, 'result': shape(ns['result'])}
    except ShapeError as exc:
        return {'ok': False, 'error': {'type': 'ResultShape', 'message': str(exc), 'line': None, 'source': None}}
    except BaseException as exc:                      # the program's own error, reported to the model
        message = re.sub(r'\. Closest: \[\]', '', str(exc))[:600]
        hint = _key_error_hint(exc, tables) if isinstance(exc, KeyError) else ''
        line, source = error_location(exc, code)
        values = _line_values(source, ns) if source and not isinstance(exc, SyntaxError) else ''
        return {'ok': False, 'error': {'type': type(exc).__name__, 'message': message, 'line': line, 'source': source, 'values': values,
                                       'hint': hint}}
    finally:
        sys.stdout, sys.stderr = real_stdout, sys.__stderr__
        run.stdout = out.getvalue()


def _limit(memory_bytes, cpu_seconds, file_bytes):
    """Resource limits set by the worker itself, first thing (no preexec_fn while the host runs threads)."""
    try:
        import resource
    except ImportError:                             # Windows dev: no rlimits, the host timeout still applies
        return
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    request = json.loads(sys.stdin.read())
    if request.get('limits'):
        _limit(*request['limits'])
    real = sys.stdout
    try:
        response = run(request)
    except BaseException as exc:                      # loading tables or encoding failed: a host-side error
        response = {'ok': False, 'error': {'type': 'HostError', 'message': f'{type(exc).__name__}: {exc}'[:2000],
                                           'line': None, 'source': None}}
    response['stdout'], response['trace'] = getattr(run, 'stdout', ''), '\n'.join(getattr(run, 'trace', []))
    real.write('\n' + MARKER + json.dumps(response, ensure_ascii=False, default=str) + '\n')
    real.flush()


if __name__ == '__main__':
    main()
