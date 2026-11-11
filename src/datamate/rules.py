"""Rulebook as units (one per non-empty line: heading, table row, paragraph, bullet), each keyed by a hash of its
words and operators: NFC, lower case, one tone placement (hoà = hòa, huỷ = hủy), the line's markdown lead (#, -, >,
"1.") and punctuation removed, while numbers (1.000) and operators (+ − > ≥ = % →) are kept, so a retyped line (bold
dropped, curly quotes, a trailing period, a table row written as a bullet) keeps its key and any changed word, number
or operator does not. The standard units are the train rulebook lines stored in assets/cookbook_train.yaml next to the
cookbook recipe that carries each one. Compared with them, a split's rulebook has:
- changes: lines with no standard match, and every line of a section whose heading is new or renamed (a rule copied
  to a new shop type applies there), listed word for word;
- gone: standard lines it no longer has (edited or removed): their recipes leave its system prompt (prompt.py);
- or, when most lines differ or many standard lines are gone (a rewrite), the full text is the rulebook and the whole
  cookbook stays.

In:  rulebook markdown, assets/cookbook_train.yaml (built from the train rulebook and the verified recipes).
Out: units, `compare` -> changes / gone / full.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

COOKBOOK = Path(__file__).with_name('assets') / 'cookbook_train.yaml'
SEPARATOR = re.compile(r'\s*\|?(\s*:?-{3,}:?\s*\|)*\s*:?-{3,}:?\s*\|?\s*')            # a whole markdown table rule
TONE = {'òa': 'oà', 'óa': 'oá', 'ỏa': 'oả', 'õa': 'oã', 'ọa': 'oạ', 'òe': 'oè', 'óe': 'oé', 'ỏe': 'oẻ', 'õe': 'oẽ',
        'ọe': 'oẹ', 'ùy': 'uỳ', 'úy': 'uý', 'ủy': 'uỷ', 'ũy': 'uỹ', 'ụy': 'uỵ'}         # old style -> new style
OLD_TONE = re.compile('(' + '|'.join(TONE) + r')(?!\w)')
I_OF = dict(zip('yýỳỷỹỵ', 'iíìỉĩị'))
Y_FINAL = re.compile(r'\b(qu|[bcdđghklmnprstvx]{1,2})([yýỳỷỹỵ])\b')                 # a syllable ending in y after a consonant
LEAD = re.compile(r'^\s*((#{1,6}|>|[-+*])\s+)?(\d+(\.\d+)*[.)]\s+)?')                     # heading/bullet/numbering
SYMBOLS = '<>≤≥=≠+−±×÷%→'
PUNCT = re.compile(rf'(?<!\d)[^\w\s{SYMBOLS}]|[^\w\s{SYMBOLS}](?!\d)|_')                  # keep 1.000, 2,5, operators
GONE_SHARE, FULL_SHARE = 0.3, 0.5


def normalize(line: str) -> str:
    s = OLD_TONE.sub(lambda m: TONE[m[1]], unicodedata.normalize('NFC', line).lower())
    s = LEAD.sub('', s, count=1).replace('->', '→')
    s = re.sub(r'[-–—]', ' − ', s)                                     # Y-1 = Y − 1 = Y–1, X–Y = X - Y
    s = Y_FINAL.sub(lambda m: m[1] + I_OF[m[2]], s).replace('mồng', 'mùng')   # tỷ = tỉ, lý = lí, quý = quí
    s = re.sub(r'(?<![\w.,:])0+(?=\d)', '', s)       # 06:00 = 6:00, tháng 03 = tháng 3; 0,05, 1.000, SP001 kept
    s = re.sub(r'(?<=\d)\s*x\s*(?=\d)', '×', s)                       # 2 x 3 = 2×3
    s = re.sub(rf'\s*([{SYMBOLS}])\s*', r' \1 ', s)                     # D+N = D + N, 12,4% = 12,4 %
    return re.sub(r'\s+', ' ', PUNCT.sub(' ', s)).strip()


def key(line: str) -> str:
    return hashlib.sha256(normalize(line).encode('utf-8')).hexdigest()[:16]


def is_unit(line: str) -> bool:
    return bool(line.strip()) and not SEPARATOR.fullmatch(line)


def units(rulebook: str):
    """[(key, line)] for every rule line (non-empty, not a table separator)."""
    return [(key(l), l) for l in rulebook.splitlines() if is_unit(l)]


@lru_cache(maxsize=None)
def load_cookbook(path: Path = COOKBOOK) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))


def train_lines(book: dict) -> list:
    """Every train rulebook line the cookbook file holds, in no particular order."""
    out = list(book['rulebook_only'])
    for s in book['sections']:
        out += [s['heading'], *s['rulebook_only'], *(r for e in s['entries'] for r in e['rules'])]
    return out


def load_train_units(path: Path = COOKBOOK) -> dict:
    """{key: train line} of the standard rulebook."""
    out = {}
    for line in train_lines(load_cookbook(path)):
        out.setdefault(key(line), line)
    return out


def _heading(line):
    s = line.lstrip()
    return len(s) - len(s.lstrip('#')) if s.startswith('#') else 0


def changes(rulebook: str, train: dict):
    """Rule lines with no train match, and every line under a new or renamed heading (the first heading is the
    document title, never a scope), each prefixed by its section heading."""
    out, section, scope, first = [], '', [], True
    for line in rulebook.splitlines():
        level = _heading(line)
        if level:
            scope = [s for s in scope if s[0] < level] + [(level, not first and key(line) not in train)]
            section, first = line.lstrip('#').strip(), False
        elif is_unit(line) and (key(line) not in train or any(new for _, new in scope)):
            out.append(f'{section}: {line.strip()}' if section else line.strip())
    return out


def compare(rulebook: str, train: dict):
    """{'changes': [...], 'gone': {standard keys missing}, 'full': bool}. A rewrite (more than FULL_SHARE of the lines
    changed, or more than GONE_SHARE of the standard lines missing) is sent whole and keeps the whole cookbook."""
    mine = units(rulebook)
    found = changes(rulebook, train)
    present = {k for k, _ in mine}
    gone = {k for k, line in train.items() if k not in present and not _heading(line)}
    if not mine or len(found) > FULL_SHARE * len(mine) or len(gone) > GONE_SHARE * max(len(train), 1):
        return {'changes': [], 'gone': set(), 'full': bool(mine)}
    return {'changes': found, 'gone': gone, 'full': False}
