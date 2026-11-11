"""Sandbox (sandbox.py, worker.py, program.py): child process with limits; errors come back with the line."""
import pytest

from datamate.data import _fingerprint, load_business
from datamate.program import drop_broken_prints
from datamate.sandbox import Limits, execute


@pytest.fixture
def tables(split, tmp_path):
    folder, calendar = split / 'data' / 'biz_1', split / 'calendar.csv'
    load_business(folder, calendar, tmp_path / 'c')
    return tmp_path / 'c' / f'biz_1-{_fingerprint(folder, calendar)}.pkl'


def run(code, tables, **limits):
    return execute(code, tables, '2026-03-20', Limits(**{'wall_seconds': 20, **limits}))


def test_program_reads_tolerant_tables_and_helpers(tables):
    r = run("df = tables['ban_hang']\nstart, end = dm.month_range(as_of)\ndf = dm.between(df, 'ngay', start, end)\n"
            "df = dm.dedup(df)\nprint(len(df))\nresult = int(df[df['trang thai'] == 'Hoàn thành']['thanh tien'].sum())", tables)
    assert r.ok and r.result == 140000 and r.stdout.strip() == '3'


def test_prints_and_imports_never_sink_a_program(tables):
    r = run("from dm import dm\nimport dm as h\nprint(f'{x[')\nprint(undefined)\nresult = h.norm('Đã HỦY')", tables)
    assert r.ok and r.result == 'da huy'
    assert 'syntax error was skipped' in r.stdout and 'print on line 4 failed' in r.stdout


def test_errors_name_the_line_and_the_fix(tables):
    r = run("df = tables['ban_hang']\nresult = df['Mã khách'].nunique()", tables)
    assert not r.ok and r.error['type'] == 'KeyError' and r.error['line'] == 2 and 'Tables: ban_hang' in r.error['hint'] and '__raw' not in r.error['hint']
    assert r.error_text().index('(line 2:') < r.error_text().index('Tables:')            # the line comes before the long hint
    assert 'never assigned result' in run('x = 1', tables).error['message']
    assert 'ambiguous' in run("result = {'a': 1}", tables).error['message']
    assert run("tables['khong co']", tables).error['type'] == 'KeyError'


def test_errors_show_the_variables_the_failing_line_reads(tables):
    r = run("df = tables['ban_hang']\nstart = dm.days_back(as_of, 7)\nresult = len(df[df['ngay'] >= start])", tables)
    assert not r.ok and r.error['line'] == 3
    text = r.error_text()
    assert 'Variables on that line' in text and 'start: tuple of 2' in text and 'df: table' in text
    assert 'pd:' not in text and 'tables:' not in text                # helpers and modules are not listed
    assert 'Variables' not in run("x = (1,\nresult = 1", tables).error_text()   # no values for a syntax error


def test_limits(tables):
    assert run('while True: pass', tables, wall_seconds=2).error['type'] == 'Timeout'
    r = run('import numpy as np\na = np.ones((80000, 80000))\nresult = 1', tables)
    assert not r.ok and r.error['type'] in ('MemoryError', 'MemoryLimit')


def test_broken_print_lines_only():
    code, dropped = drop_broken_prints("x = 1\nprint(f'{x:,d} {\"a\"}')\n  print(f'{')\nresult = x")
    assert dropped and code.split('\n')[-1] == 'result = x'
    assert drop_broken_prints('x = (1\nresult = x')[1] == []


def test_table_names_are_also_variables(tables):
    r = run("result = int(len(ban_hang) == len(tables['ban_hang']))", tables)
    assert r.ok and r.result == 1


def test_key_error_hint_survives_a_program_that_rebinds_tables(tables):
    run = execute("tables = {'x': pd.DataFrame({'a': [1]})}\nresult = tables['x']['b'].sum()", tables, '2026-01-01', Limits())
    assert not run.ok and run.error['type'] == 'KeyError'



def test_every_top_level_assignment_is_traced(tables):
    r = run("df = tables['ban_hang']\nn, m = len(df), 2\nfor i in range(2):\n    k = i\nn += 1\nresult = df['khong co']", tables)
    lines = r.trace.splitlines()
    assert not r.ok and lines[0].startswith('line 1 df: table') and 'line 2 n: int' in r.trace and 'line 2 m: int 2' in r.trace
    assert 'line 5 n:' in r.trace and ' k:' not in r.trace                          # top level only
    assert run("x = 1\nresult = x", tables).trace == 'line 1 x: int 1\nline 2 result: int 1'
