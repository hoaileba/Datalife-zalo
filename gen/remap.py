"""Rename map of a reskinned shop (gen.reskin) applied to text: teacher code, teacher reasoning, README, gold answers.

NameMap(names, labels): `names` = old -> new table, column, file and sheet names; `labels` = old -> new status/payment
labels (cell values). Both are exact strings of the original shop.

- map_code(code): string literals only (tokenize; f-string parts too): a literal equal to an old name/label (exact,
  else equal after fold when that is unambiguous and the literal is not a Python identifier such as 'status', which
  is usually a name the program made: the agent's tables read columns case/accent-tolerantly) becomes the new one; inside longer literals, quoted or distinctive occurrences (see map_prose); attribute access `df.old_col`
  becomes `df.new_col` when the new name is an identifier. Comments are mapped as prose. Variable names stay.
- map_prose(text): quoted occurrences ('x', "x", `x`, **x**, “x”) of every name and label; unquoted occurrences of
  distinctive names (snake_case, CamelCase, ALLCAPS, file names, several words not opening a sentence). A single
  ordinary word ("Hàng", "cash") is left: it reads as a plain word.
- stale(code, prose): what still refers to the old shop after mapping (a sample with any is dropped): an old name or
  label in a code literal or quoted in prose, a distinctive old name anywhere, an attribute access to an old column,
  a code literal that is a fragment of an old label but of no current label (`.str.contains('hủy')`).
- map_answer(gold): labels inside string/list/table answers (and aliases); None when the answer is a renamed name.
"""
from __future__ import annotations

import io
import keyword
import re
import tokenize

from datamate.helpers import norm

QUOTES = (("'", "'"), ('"', '"'), ('`', '`'), ('**', '**'), ('“', '”'), ('‘', '’'), ('«', '»'))
WORD = r'[\wÀ-ỹ]'
COMPANIONS = ('__raw', '__unit', '__group_total')          # columns the reader adds next to a column
SENTENCE_START = re.compile(r'(?:^|[.!?:;]\s+|\n\s*(?:[-*+]\s+|\d+[.)]\s+)?|\(\s*)$')


def distinctive(name: str) -> bool:
    """A name that cannot be an ordinary word of the prose: snake_case, CamelCase, ALLCAPS (2+ letters), digits,
    a file name, or (checked at the match) several words."""
    letters = [c for c in name if c.isalpha()]
    return bool('_' in name or any(a.islower() and b.isupper() for a, b in zip(name, name[1:])) or re.search(r'\d', name)
                or (len(letters) >= 2 and ' ' not in name and all(c.isupper() for c in letters))
                or re.search(r'\.(csv|xlsx|sqlite|db)$', name, re.I))


def ordinary_phrase(name: str) -> bool:
    """Several plain words written like a sentence ("Khách hàng", "Tổng tiền"): could open a sentence of prose."""
    return bool(re.fullmatch(r'[^\W\d_][^\W\d_ ]*( [^\W\d_]+)+', name)) and name[1:] == name[1:].lower()


def _bounded(alts):
    """Regex for any of alts on word boundaries (letters with Vietnamese marks count as word characters)."""
    body = '|'.join(re.escape(a) for a in sorted(alts, key=len, reverse=True))
    return re.compile(rf'(?<!{WORD})(?:{body})(?!{WORD})')


class NameMap:
    def __init__(self, names: dict, labels: dict, keep=()):
        """keep: strings of the shop that were NOT renamed (headers, tables, labels): an old string inside one of them
        ("trả hàng" inside the label "Đã trả hàng") is part of a name that stays, never replaced."""
        self.names = {k: v for k, v in names.items() if k != v}
        self.labels = {k: v for k, v in labels.items() if k != v}
        both = set(self.names) & set(self.labels)
        if both:
            raise ValueError(f'a string is both a name and a label: {sorted(both)[:3]}')
        self.all = {**self.names, **self.labels}
        self.new = set(self.all.values())
        olds = [norm(o).split() for o in self.all]
        self.keep = sorted({k for k in keep if k and k not in self.all and k not in self.new and len(k) <= 200
                            and any(_contains(norm(k).split(), o) for o in olds if o)}, key=len, reverse=True)
        folded = {}
        for old in self.all:
            folded.setdefault(norm(old), set()).add(old)
        kept = {norm(k) for k in keep if k and k not in self.all}          # a name that stays wins its spellings
        self.folded = {k: next(iter(v)) for k, v in folded.items() if len(v) == 1 and k and k not in kept}
        self._new_folded = {norm(v) for v in self.new}
        self._quoted = None
        self._new_re = None
        self._label_frags = None

    def __bool__(self):
        return bool(self.all)

    # ------------------------------------------------------------ prose
    def _pattern(self):
        """One regex: every quoted form of every old string, then the bare distinctive ones; one left-to-right pass
        so a replacement is never rescanned ("SL" -> "SL bán" stays "SL bán")."""
        if self._quoted is None:
            olds = '|'.join(re.escape(o) for o in sorted(self.all, key=len, reverse=True)) or r'(?!x)x'
            parts = [rf'(?<!{WORD})(?P<keep>' + '|'.join(re.escape(k) for k in self.keep) + rf')(?!{WORD})'] if self.keep else []
            parts += [re.escape(a) + f'(?P<q{i}>{olds})' + re.escape(b) for i, (a, b) in enumerate(QUOTES)]
            bare = [o for o in self.names if distinctive(o) or ' ' in o.strip()] + \
                   [o for o in self.labels if distinctive(o) or (' ' in o.strip() and o != o.lower())]
            # a lowercase label ("trả hàng") is also the plain word of a rule: replaced only when quoted
            if bare:
                body = '|'.join(re.escape(o) for o in sorted(bare, key=len, reverse=True))
                parts.append(rf'(?<!{WORD})(?P<bare>{body})(?!{WORD})')
            self._quoted = re.compile('|'.join(parts))
        return self._quoted

    def _matches(self, text):
        """(match, quote index or None, old string) of every reference, sentence-opening plain phrases skipped."""
        for m in self._pattern().finditer(text):
            if 'keep' in m.re.groupindex and m.group('keep') is not None:
                continue                         # a name of the shop that was not renamed
            if 'bare' in m.re.groupindex and m.group('bare') is not None:
                old = m.group('bare')
                if ordinary_phrase(old) and not distinctive(old) and SENTENCE_START.search(text[:m.start()][-40:]):
                    continue                     # "Khách hàng nợ nhiều nhất..." opens a sentence: plain words
                yield m, None, old
            else:
                i = next(k for k in range(len(QUOTES)) if m.group(f'q{k}') is not None)
                yield m, i, m.group(f'q{i}')

    def map_prose(self, text: str) -> str:
        if not self.all or not text:
            return text
        out, last = [], 0
        for m, i, old in self._matches(text):
            out.append(text[last:m.start()])
            out.append(self.all[old] if i is None else QUOTES[i][0] + self.all[old] + QUOTES[i][1])
            last = m.end()
        out.append(text[last:])
        return ''.join(out)

    # ------------------------------------------------------------ code
    def _literal(self, content: str):
        """New content of a whole string literal, or None to map it as text."""
        if content in self.all:
            return self.all[content]
        f = norm(content)
        if f in self.folded and content.strip() == content and not content.isidentifier():
            return self.all[self.folded[f]]           # 'so luong' for 'Số lượng'; never 'status' (a name of the program's own)
        for suffix in COMPANIONS:
            if content.endswith(suffix) and content[:-len(suffix)] in self.names:
                return self.names[content[:-len(suffix)]] + suffix
        return None

    def map_code(self, code: str) -> str:
        if not self.all or not code:
            return code
        try:
            toks = list(tokenize.generate_tokens(io.StringIO(code).readline))
        except (tokenize.TokenError, SyntaxError, IndentationError):
            return self._map_code_regex(code)
        lines = code.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        pos = lambda rc: offsets[rc[0] - 1] + rc[1]
        edits = []
        prev = None
        for t in toks:
            if t.type == tokenize.STRING:
                new = self._string_token(t.string)
                if new != t.string:
                    edits.append((pos(t.start), pos(t.end), new))
            elif t.type == getattr(tokenize, 'FSTRING_MIDDLE', -1):
                new = self.map_prose(t.string)
                if new != t.string:
                    edits.append((pos(t.start), pos(t.end), new))
            elif t.type == tokenize.COMMENT:
                new = self.map_prose(t.string)
                if new != t.string:
                    edits.append((pos(t.start), pos(t.end), new))
            elif t.type == tokenize.NAME and prev is not None and prev.type == tokenize.OP and prev.string == '.':
                new = self.names.get(t.string)
                if new and new.isidentifier() and not keyword.iskeyword(new):
                    edits.append((pos(t.start), pos(t.end), new))
            if t.type not in (tokenize.NL, tokenize.COMMENT):
                prev = t
        for a, b, new in sorted(edits, reverse=True):
            code = code[:a] + new + code[b:]
        return code

    def _string_token(self, tok: str) -> str:
        m = re.match(r'(?is)^([rbu]*)("""|\'\'\'|"|\')(.*)\2$', tok)
        if not m:
            return tok
        prefix, q, body = m.groups()
        if 'b' in prefix.lower():
            return tok
        raw = 'r' in prefix.lower()
        if not raw and '\\' in body:
            return tok if self._literal(body) is None else tok      # escapes: leave (rare in names)
        whole = self._literal(body)
        if whole is not None:
            new_body = whole
        else:
            new_body = self.map_prose(body)
        if new_body == body:
            return tok
        if q in new_body or (not raw and '\\' in new_body):
            return tok                                            # cannot requote safely: stale check decides
        return prefix + q + new_body + q

    def _map_code_regex(self, code: str) -> str:
        """Unparsable code (a cut or broken failed turn): quoted literals only."""
        for a, b in (("'", "'"), ('"', '"')):
            body = '|'.join(re.escape(o) for o in sorted(self.all, key=len, reverse=True))
            code = re.sub(re.escape(a) + f'({body})' + re.escape(b), lambda m: a + self.all[m.group(1)] + b, code)
        return code

    # ------------------------------------------------------------ checks
    def _fragments(self):
        if self._label_frags is None:
            new_words = [norm(v).split() for v in self.labels.values()]
            frags = set()
            for old in self.labels:
                w = norm(old).split()
                for i in range(len(w)):
                    for j in range(i + 1, len(w) + 1):
                        frag = w[i:j]
                        if not any(_contains(nw, frag) for nw in new_words):
                            frags.add(' '.join(frag))
            self._label_frags = frags
        return self._label_frags

    def stale(self, code: str = '', prose: str = '') -> list:
        """Old references left after mapping (empty: clean)."""
        out = []
        masked = self._mask
        if code:
            try:
                toks = list(tokenize.generate_tokens(io.StringIO(code).readline))
            except (tokenize.TokenError, SyntaxError, IndentationError):
                toks = []
                out += [f'code:{o}' for o in self.all if re.search(r'([\'"])' + re.escape(o) + r'\1', code)]
            prev = None
            for t in toks:
                if t.type == tokenize.STRING:
                    m = re.match(r'(?is)^([rbu]*)("""|\'\'\'|"|\')(.*)\2$', t.string)
                    body = m.group(3) if m else t.string
                    out += self._stale_literal(body)
                elif t.type == getattr(tokenize, 'FSTRING_MIDDLE', -1):
                    out += [f'code:{x}' for x in self._stale_text(masked(t.string))]
                elif t.type == tokenize.NAME and prev is not None and prev.type == tokenize.OP and prev.string == '.' \
                        and t.string in self.names:
                    out.append(f'attr:{t.string}')
                if t.type not in (tokenize.NL, tokenize.COMMENT):
                    prev = t
        if prose:
            out += [f'prose:{x}' for x in self._stale_text(masked(prose))]
        return sorted(set(out))

    def _stale_literal(self, body):
        if body in self.keep or body in self.new or any(body.endswith(x) and body[:-len(x)] in self.new for x in COMPANIONS):
            return []
        f = norm(body)
        if body in self.all or (f in self.folded and f not in self._new_folded and not body.isidentifier()):
            return [f'code:{body}']
        out = [f'code:{x}' for x in self._stale_text(self._mask(body))]
        parts = [p for p in re.split(r'[|()\[\]^$\\]+', body) if p.strip()]
        for p in parts or [body]:
            fp = norm(p)
            if fp and fp in self._fragments() and len(fp) >= 2:
                out.append(f'fragment:{p}')
        return out

    def _mask(self, text):
        """Blank out the new names (on word boundaries) so an old name inside a new one ("SL" in "SL bán") is not
        reported; a new name inside a longer word ("QuyDoi" in "SLQuyDoi") is left."""
        if self._new_re is None:
            self._new_re = _bounded([n for n in self.new if n]) if any(self.new) else False
        return self._new_re.sub(lambda m: '\0' * len(m.group(0)), text) if self._new_re else text

    def _stale_text(self, text):
        return [old for _, _, old in self._matches(text)]

    # ------------------------------------------------------------ answers
    def map_value(self, v):
        if not isinstance(v, str):
            return v
        if v in self.labels:
            return self.labels[v]
        f = norm(v)
        old = self.folded.get(f)
        return self.labels[old] if old in self.labels else v

    def answer_names(self, v) -> bool:
        """The answer is (or holds) a renamed table/column/file name: its gold cannot be mapped safely."""
        vals = v if isinstance(v, list) else [v]
        return any(isinstance(x, str) and (x in self.names or (norm(x) in self.folded and self.folded[norm(x)] in self.names))
                   for x in vals)

    def map_answer(self, gold: dict):
        """Gold with renamed labels mapped (answer and alias); None when the answer names a renamed table/column."""
        g = dict(gold)
        t, a = g.get('type'), g.get('answer')
        if t == 'string':
            if self.answer_names(a):
                return None
            g['answer'] = self.map_value(a)
            g['alias'] = [self.map_value(x) for x in g.get('alias') or []]
        elif t == 'list' and isinstance(a, list):
            if any(self.answer_names(x) for x in a):
                return None
            g['answer'] = [self.map_value(x) for x in a]
            if isinstance(g.get('alias'), list):
                g['alias'] = [[self.map_value(y) for y in x] if isinstance(x, list) else self.map_value(x) for x in g['alias']]
        elif t == 'table' and isinstance(a, dict):
            rows = a.get('rows') or []
            if any(self.answer_names(c) for r in rows for c in r):
                return None
            g['answer'] = {**a, 'rows': [[self.map_value(c) for c in r] for r in rows]}
            if isinstance(g.get('alias'), list):
                g['alias'] = [[self.map_value(y) for y in x] if isinstance(x, list) else self.map_value(x) for x in g['alias']]
        return g


def _contains(words, frag):
    n = len(frag)
    return any(words[i:i + n] == frag for i in range(len(words) - n + 1))
