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
NO_RESULT = ('The program ran but never assigned result: end it with result = {"type": "<type>", "answer": <value>} (a look: result = {"type": "look"})')


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

    kit = types.SimpleNamespace(**{n: getattr(helpers, n) for n in helpers.__all__})
    for name in ('kit', 'dm'):                       # `import kit` / `from kit import ...` resolve to the helpers
        module = types.ModuleType(name); module.__dict__.update(vars(kit)); setattr(module, name, kit)
        sys.modules[name] = module
    ns = {'__name__': '__agent__', 'pd': pd, 'np': np, 'kit': kit, 'dm': kit, 'datetime': datetime, 'math': math,
          'Decimal': Decimal, 'as_of': pd.Timestamp(as_of), 'tables': Tables(),
          'round_decimal': round_decimal, 'round_half_up': round_half_up, 'readme': getattr(business, 'readme', '') or '',
          'true': True, 'false': False, 'null': None}     # a result dict written the JSON way still runs
    for name in business.tables:                     # don_hang IS tables['don_hang'] (models write both)
        if name.isidentifier() and name not in ns:
            ns[name] = ns['tables'][name]
    return ns


def _attribute_hint(exc):
    """`df.dedup(...)`: a kit function called as a method of a table or column."""
    from .helpers import __all__ as kit_names
    found = re.search(r"object has no attribute '(\w+)'", str(exc))
    if found and found.group(1) in kit_names and re.search(r"'(DataFrame|Series|TolerantFrame)' object", str(exc)):
        name = found.group(1)
        return f'{name} is a kit function, not a method of a table: write kit.{name}(df, ...), not df.{name}(...).'
    return ''


def _key_error_hint(exc, tables):
    """Say which loaded table has the missing column, and list the loaded tables' columns."""
    from .helpers import norm
    quoted = re.search(r"'([^']+)'", str(exc.args[0])) if exc.args else None
    key = norm(quoted.group(1) if quoted else str(exc.args[0] if exc.args else ''))
    owners = [n for n, f in tables.loaded.items() if any(norm(c) == key for c in f.columns)]
    cols = lambda f: [str(c) for c in f.columns if not str(c).endswith('__raw') and f[c].notna().any()]
    return (f'Found in table(s): {owners}. ' if owners else '') + 'Tables: ' + '; '.join(f'{n}: {cols(f)}' for n, f in tables.loaded.items())


def _evidence(business, as_of):
    """Rows and date ranges of every shop table (the shared calendar left out): what an 'unanswerable' is checked against."""
    out = [f'as_of {as_of}: records dated after it have not happened. A date column may be an attribute (an expiry, a '
           'birth date), not an event: judge by the dates of the asked kind of event.']
    import pandas as pd
    cut = pd.Timestamp(as_of) + pd.Timedelta(days=1)
    for name, frame in business.tables.items():
        if name == 'calendar':
            continue
        dates = [_range(c, frame[c], cut) for c in frame.columns
                 if str(frame[c].dtype).startswith('datetime64') and frame[c].notna().any()][:4]
        out.append(f"{name}: {len(frame)} rows" + (f"; dates {', '.join(dates)}" if dates else ''))
    return out[:41]


def _range(name, col, cut):
    """'col first..last' up to as_of (the end of that day), with the count of later rows."""
    seen, later = col[col < cut], int((col >= cut).sum())
    span = f"{seen.min():%Y-%m-%d}..{seen.max():%Y-%m-%d}" if seen.notna().any() else 'none up to as_of'
    return f"{name} {span}" + (f" (+{later} rows after as_of)" if later else '')


HIDDEN = {'pd', 'np', 'kit', 'dm', 'datetime', 'math', 'Decimal', 'tables', 'round_decimal', 'round_half_up', '__builtins__', '__name__', '__trace__', 'readme', 'true', 'false', 'null'}


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


COLUMN_LABELS = set()                            # labels of the shop's tables, filled by run()


def _bound_name(name, value):
    """A BIND constant that names columns (ORDER_DATE = 'Ngày bán'): left out of traces. Constants holding values
    (codes, labels, dates) stay visible: an error must show them."""
    texts = value if isinstance(value, (list, tuple)) else [value]
    return name.isupper() and bool(texts) and all(isinstance(v, str) and v in COLUMN_LABELS for v in texts)


def _line_values(source, ns):
    """'name: type value' for the variables the failing line reads (at most 8), or ''."""
    import ast
    try:
        names = [n.id for n in ast.walk(ast.parse(source.strip().rstrip(':'))) if isinstance(n, ast.Name)]
    except SyntaxError:
        return ''
    seen = [n for n in dict.fromkeys(names) if n in ns and n not in HIDDEN and not _bound_name(n, ns[n])][:8]
    return '; '.join(f'{n}: {_describe(ns[n])}' for n in seen)[:1200]


def run(request):
    import pickle
    from .program import error_location, tolerant_compile
    from . import helpers
    from .shape import ShapeError, shape, typed
    out = _Capture(request.get('max_stdout', 20000))
    with open(request['tables_path'], 'rb') as f:
        business = pickle.load(f)
    ns = _namespace(business, request['as_of'])
    COLUMN_LABELS.update(str(c) for f in business.tables.values() for c in f.columns)
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
            trail.extend(f'line {line} {name}: {brief(ns[name])}'[:300] for name in names if name in ns and not _bound_name(name, ns[name]))
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
        value = ns['result']
        if not request.get('typed', True) and not (isinstance(value, dict) and 'type' in value):
            return {'ok': True, 'result': shape(value)}      # replay of an old program: a plain value
        result = typed(value)
        said = helpers.says_unanswerable(result['answer'])
        if result['type'] == 'unanswerable' or said:      # evidence for the host's check: the shop's tables
            result['evidence'] = _evidence(business, request['as_of'])
        return {'ok': True, 'result': result}
    except ShapeError as exc:
        return {'ok': False, 'error': {'type': 'ResultShape', 'message': str(exc), 'line': None, 'source': None}}
    except BaseException as exc:                      # the program's own error, reported to the model
        message = re.sub(r'\. Closest: \[\]', '', str(exc))[:600]
        hint = _key_error_hint(exc, tables) if isinstance(exc, KeyError) else _attribute_hint(exc) if isinstance(exc, AttributeError) else ''
        line, source = error_location(exc, code)
        if not hint and helpers.MASK_HINT not in message and (source and 'kit.between(' in source and not isinstance(exc, (KeyError, SyntaxError))
                                                             or '_indexed_same' in str(exc)):          # mask &= <a table>: pandas fails with this message
            hint = 'A mask was combined with a table, not with a column. ' + helpers.MASK_HINT
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
