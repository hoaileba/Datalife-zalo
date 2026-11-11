"""Project criteria: size limits, one-way dependencies, MAP.md covers every module."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src' / 'datamate'
MODULES = sorted(p for p in SRC.glob('*.py') if p.name != '__init__.py')
# Lower layers must not import higher ones.
LAYER = {'values': 0, 'grids': 1, 'windows': 0.5, 'names': 0.5, 'layout': 1.5, 'totals': 1, 'columns': 1, 'helpers': 1, 'program': 1, 'shape': 1, 'config': 0, 'rules': 0, 'data': 2, 'notes': 2.5, 'answer': 2,
         'worker': 2, 'catalog': 3, 'sandbox': 3, 'llm': 1, 'prompt': 3, 'eval': 1, 'solve': 4, 'replay': 5, 'runner': 5}


def test_size_limits():
    # no total line budget (user, 11/11: "không giới hạn code"); per-module and per-function limits stay
    for p in MODULES:
        assert len(p.read_text().splitlines()) <= 400, p.name
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.FunctionDef):
                assert node.end_lineno - node.lineno + 1 <= 60, f'{p.name}:{node.name}'


def test_dependencies_point_down():
    for p in MODULES:
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                assert LAYER[node.module] < LAYER[p.stem], \
                    f'{p.stem} imports {node.module}'


def test_every_module_is_mapped_and_documented():
    mapped = (ROOT / 'MAP.md').read_text()
    for p in MODULES:
        assert f'`{p.name}`' in mapped, p.name
        assert ast.get_docstring(ast.parse(p.read_text())), p.name
