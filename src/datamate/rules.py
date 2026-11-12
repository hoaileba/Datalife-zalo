"""Rulebook as units (one per non-empty line: heading, table row, paragraph, bullet), each keyed by a hash of its
words and operators: NFC, lower case, one tone placement (hoà = hòa, huỷ = hủy), the line's markdown lead (#, -, >,
"1.") and punctuation removed, while numbers (1.000) and operators (+ − > ≥ = % →) are kept, so a retyped line (bold
dropped, curly quotes, a trailing period, a table row written as a bullet) keeps its key and any changed word, number
or operator does not. The standard units are the train rulebook lines stored in assets/cookbook_train.yaml next to the
cookbook recipe that carries each one. Compared with them, a split's rulebook has:
- changes: lines with no standard match, and every line of a section whose heading is new or renamed (a rule copied
  to a new shop type applies there), listed word for word;
- gone: standard lines it no longer has (edited or removed): their recipes leave its system prompt (prompt.py);
- a retyped line (other words, a table row written as a bullet) is aligned with the standard rule of the same NAME (a
  table row's first cell, a bullet's or paragraph's leading bold or code words): with the same meaning (same bold
  phrases, numbers, operators and polarity words, and most words in common) it keeps the standard recipe; otherwise it
  is a change and the standard rule is gone. Doubtful cases count as changed (a recipe lost costs less than a wrong one);
- only when many standard lines have no counterpart at all (neither the same text nor a rule of the same name: a
  rulebook of another structure) the full text is the rulebook and the whole cookbook stays.

In:  rulebook markdown, assets/cookbook_train.yaml (built from the train rulebook and the verified recipes).
Out: units, `compare` -> changes / gone / full.
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
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
NAMED = re.compile(r'^(?:[-+*]\s+|\d+[.)]\s+)?(?:\*\*(?P<b>[^*]+?)\*\*|`(?P<c>[^`]+)`)\s*(?P<body>.*)$')
POLARITY = ('không', 'chỉ', 'trừ', 'cộng', 'gồm', 'kể cả', 'bỏ', 'chưa', 'vẫn', 'mọi', 'cả', 'trước', 'sau', 'tính')
POLARITY_RE = [re.compile(rf'(?<!\w){p}(?!\w)') for p in POLARITY]
BOLD = re.compile(r'\*\*(.+?)\*\*')
COLUMN_LABEL = re.compile(r'^\s*(mặc định|nghĩa|hiểu là)\s*:\s*', re.I)   # a standard table's column name, as a label
SAME_RATIO = 0.8                                   # share of words in common for a retyped line to keep its meaning


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


def split_rule(line: str):
    """(name, body) of a rule line: a table row's first cell and the other cells, or the leading bold or `code` words of
    a bullet or paragraph and the rest; (None, line) when the line has no name."""
    s = line.strip()
    if s.startswith('|'):
        cells = [c.strip() for c in s.strip('|').split('|')]
        if len(cells) >= 2 and cells[0]:
            return cells[0], ' | '.join(cells[1:])
    m = NAMED.match(s)
    if m and (m['b'] or m['c']).strip():
        body = COLUMN_LABEL.sub('', re.sub(r'^\s*[:—–-]+\s*', '', m['body']))
        return (m['b'] or m['c']).strip(), body
    return None, s


def name_key(name: str) -> str:
    return normalize(name.replace('**', ''))


def _figures(norm):
    return sorted(t for t in norm.split() if any(c.isdigit() for c in t) or t in SYMBOLS)


def same_meaning(a: str, b: str) -> bool:
    """Two bodies of one rule say the same: the same bold phrases, numbers, operators and polarity words (không,
    chỉ, kể cả...), and at least SAME_RATIO of the words in common. Anything else counts as a changed rule."""
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return True
    if sorted(map(normalize, BOLD.findall(a))) != sorted(map(normalize, BOLD.findall(b))) or _figures(na) != _figures(nb):
        return False
    if any(len(p.findall(na)) != len(p.findall(nb)) for p in POLARITY_RE):
        return False
    return SequenceMatcher(None, na.split(), nb.split(), autojunk=False).ratio() >= SAME_RATIO


@lru_cache(maxsize=8)
def _names(items):
    """{name key: (train key, body)} of the standard rule lines whose name is unique (header rows like "Luật" repeat)."""
    seen = {}
    for k, line in items:
        if _heading(line):
            continue
        name, body = split_rule(line)
        if name:
            seen.setdefault(name_key(name), []).append((k, body))
    return {n: v[0] for n, v in seen.items() if len(v) == 1}


def align(rulebook: str, train: dict):
    """[(section, line, status, train key)] for every rule line: status 'same' (the standard text, or a retyped rule of
    the same name and meaning), 'edited' (a standard rule's name with another meaning), 'new' (no standard rule of
    that text or name), 'scoped' (any line under a new or renamed heading: the first heading is the title, never a
    scope)."""
    names = _names(tuple(train.items()))
    out, section, scope, first = [], '', [], True
    for line in rulebook.splitlines():
        level = _heading(line)
        if level:
            scope = [s for s in scope if s[0] < level] + [(level, not first and key(line) not in train)]
            section, first = line.lstrip('#').strip(), False
            continue
        if not is_unit(line):
            continue
        k = key(line)
        if any(new for _, new in scope):
            out.append((section, line, 'scoped', k if k in train else None))
        elif k in train:
            out.append((section, line, 'same', k))
        else:
            name, body = split_rule(line)
            hit = names.get(name_key(name)) if name else None
            if hit is None:
                out.append((section, line, 'new', None))
            else:
                out.append((section, line, 'same' if same_meaning(body, hit[1]) else 'edited', hit[0]))
    return out


def changes(rulebook: str, train: dict):
    """Rule lines a model must read beyond the cookbook (new, edited, or under a new heading), each prefixed by its
    section heading."""
    return [f'{s}: {line.strip()}' if s else line.strip()
            for s, line, status, _ in align(rulebook, train) if status != 'same']


def compare(rulebook: str, train: dict):
    """{'changes': [...], 'gone': {standard keys missing}, 'full': bool}. Standard lines with no counterpart at all
    (neither their text nor a rule of their name) beyond GONE_SHARE, or new unnamed lines beyond FULL_SHARE of the
    rulebook, make it a rulebook of another structure: sent whole, with the whole cookbook."""
    rows = align(rulebook, train)
    if not rows:                                   # nothing but headings (or nothing): not the standard rules
        return {'changes': [], 'gone': set(), 'full': bool(units(rulebook))}
    edited = {k for _, _, status, k in rows if k and status == 'edited'}
    kept = {k for _, _, status, k in rows if k and status in ('same', 'scoped')} - edited     # an edit wins over a copy
    touched = {k for _, _, status, k in rows if k}                        # same, edited or scoped: has a counterpart
    standard = {k for k, line in train.items() if not _heading(line)}
    unmatched = standard - touched
    new = sum(status == 'new' for *_, status, _ in rows)
    if len(unmatched) > GONE_SHARE * max(len(train), 1) or new > FULL_SHARE * len(rows):
        return {'changes': [], 'gone': set(), 'full': True}
    found = [f'{s}: {line.strip()}' if s else line.strip() for s, line, status, _ in rows if status != 'same']
    return {'changes': found, 'gone': standard - kept, 'full': False}
