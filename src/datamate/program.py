"""Diagnostic lines must not sink a program: deterministic source fixes applied inside the sandbox before compiling.

print() is diagnostic only (the answer is `result`), so:
- a print line that does not parse (typically a broken f-string) is replaced by `pass` at the same indentation;
- a top-level print whose arguments raise at run time prints a warning instead of failing the program.
Line numbers never move, so error locations still point at the model's own lines. Every change is reported in
stdout. Nothing else in the program is touched.
"""
from __future__ import annotations

import ast
import re

MAX_DROPPED = 10
PRINT_LINE = re.compile(r'^(\s*)print\s*\(')


def drop_broken_prints(code):
    """(code, dropped line numbers). Stops at the first syntax error that is not on a print line; the returned
    code then still fails to parse, at that real error."""
    lines, dropped = code.split('\n'), []
    for _ in range(MAX_DROPPED):
        try:
            ast.parse('\n'.join(lines))
            return '\n'.join(lines), dropped
        except SyntaxError as exc:
            number = exc.lineno
            if not number or number > len(lines): break
            match = PRINT_LINE.match(lines[number - 1])
            if not match or number in dropped: break
            lines[number - 1] = match.group(1) + 'pass'
            dropped.append(number)
    return '\n'.join(lines), dropped


def guard_prints(tree):
    """Wrap each top-level print(...) statement so an exception in its arguments only prints a warning."""
    body = []
    for stmt in tree.body:
        if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == 'print'):
            warn = ast.parse(f"print('[host] print on line {stmt.lineno} failed (' + type(__print_error__).__name__ + ': ' "
                             "+ str(__print_error__)[:300] + '); ignored')").body[0]       # the error says what to fix (a column name)
            stmt = ast.Try(body=[stmt], handlers=[ast.ExceptHandler(ast.Name('Exception', ast.Load()), '__print_error__', [warn])],
                           orelse=[], finalbody=[])
            ast.copy_location(stmt, stmt.body[0]); ast.fix_missing_locations(stmt)
        body.append(stmt)
    tree.body = body
    return tree


def tolerant_compile(code, filename='<agent>'):
    """(code object, notes), with the step trace (add_trace). Raises the original SyntaxError when the program does not parse."""
    fixed, dropped = drop_broken_prints(code)
    tree = guard_prints(ast.parse(fixed, filename))
    notes = [f'[host] line {n}: print with a syntax error was skipped' for n in dropped]
    return compile(add_trace(tree), filename, 'exec'), notes


def add_trace(tree):
    """`__trace__(line, names)` after each top-level assignment: a failing or flagged program comes back with the state of every step."""
    body = []
    for stmt in tree.body:
        body.append(stmt)
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, (ast.AugAssign, ast.AnnAssign)) else []
        names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]
        if names:
            body.append(ast.fix_missing_locations(ast.copy_location(ast.Expr(ast.Call(ast.Name('__trace__', ast.Load()), [ast.Constant(stmt.lineno), ast.Constant(tuple(names))], [])), stmt)))
    tree.body = body
    return tree


def error_location(exc, code, filename='<agent>'):
    """(line number, source line) of the program line where `exc` was raised, or (None, None)."""
    import traceback
    number = None
    if isinstance(exc, SyntaxError) and exc.filename == filename:
        number = exc.lineno
    else:
        for frame in traceback.extract_tb(exc.__traceback__):
            if frame.filename == filename:
                number = frame.lineno
    lines = code.split('\n')
    if number is None or not 1 <= number <= len(lines):
        return None, None
    return number, lines[number - 1].strip()[:300]
