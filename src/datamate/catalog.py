"""What the model sees about a business: a lean catalog of tables and columns, the README and the rulebook,
and the values the question mentions (lookup). Built once per business; identical for all its questions so the
serving engine's prefix cache covers it.

In:  `Business` (data.py), rulebook text, question text.
Out: catalog dict {'notes', 'schemas', 'documents'} and `lookup(question, business)` matches.
"""
from __future__ import annotations

from .data import RAW_SUFFIX, SECTION_COL, SOURCE_COL, START_COL, UNIT_SUFFIX
from .helpers import norm
from .notes import data_notes

NOTES = (
    'Tables are read from the source files with their ORIGINAL column headers. Only format fixes were applied: '
    'header detection (a two-row header joined as "upper / lower"; rows above the header shown as text_above_header: '
    'they may say what the export covers); rows that are not records removed, counted in dropped_rows with examples: '
    'blank, repeated header, totals (a total label, or numbers equal to the sum of their block), one-cell notes '
    'after the data, signature footers; one-cell rows heading sections become the column '
    f'"{SECTION_COL}"; partitions of one table (monthly sheets, files named _1/_2/_2026) concatenated, with '
    f'"{SOURCE_COL}" naming the origin sheet/file. Numbers, quantities and dates are parsed from content (decimal '
    'mark and day/month order as the column\'s own cells show, noted when it matters); when the '
    f'source held text, "<col>{RAW_SUFFIX}" keeps the original (listed only where some cells did not parse). '
    f'Quantities written with a unit ("2 gói") keep the unit in "<col>{UNIT_SUFFIX}". Line tables where only the '
    'first line of an order carries the order cells (id, date, status, customer) have those cells filled down to '
    f'the following lines of the order (noted on the columns; "{START_COL}" marks the lines that carried them). NOT '
    'applied: duplicate removal, status normalization, entity merging, unit conversion: apply the rulebook and '
    'README in code.')
MAX_MATCHES, MAX_PER_PHRASE = 15, 5
UNREADABLE = ('These files of the shop could not be read: their rows are in no table. A question that needs them may '
              'be unanswerable.')
# Everyday question words (folded): a partial-match phrase made only of these and numbers ("la bao", "thang 8",
# "6 2025") names nothing in the data.
FUNCTION_WORDS = set("""la bao nhieu may co khong cua cho va voi trong tu den het ngay thang nam quy tuan gio hom qua nay
mai truoc sau thi ra vao mot cac nhung nhat hon kem bi duoc da dang se tong cong so tien don hang ban mua khach shop quan
cua ai gi nao the nhu vay oi a ve len xuong moi tung lan ky dau cuoi giua theo tren duoi qua lai con
thu binh trung doanh ti le phan tram gia nhap ton kho lai lo huy
hai ba bon tu sau bay tam chin muoi tram nghin ngan trieu ty
hop vi vien goi chai tuyp ong lon thung ly cai""".split())       # packaging alone names no product
LABEL_WORDS = {   # folded words that name a status or payment concept in a label: grouping HINTS, never applied to data
    'order status': {'cancelled': 'huy|cancel|cancelled|canceled|void', 'returned': 'tra hang|hoan tra|doi tra|tra lai|return|returned|refund|hoan tien',
                     'completed': 'hoan thanh|xong|completed|complete|done|success|thanh cong|da giao|delivered',
                     'delivering': 'dang giao|cho giao|dang van chuyen|van chuyen|shipping|delivering|in transit', 'pending pickup': 'cho lay|cho xu ly|pending|dat truoc|preorder'},
    'payment': {'cash': 'tien mat|cash', 'transfer': 'chuyen khoan|transfer|bank', 'cod': 'cod', 'debt': 'ghi no|cong no|no|debt|credit|tra sau',
                'e-wallet': 'vi dien tu|ewallet|e wallet|momo|zalopay|vnpay|shopeepay'}}
HONORIFICS = set('anh chị cô chú bác ông bà'.split())   # accented: "chị Mai Lan" names someone, "có", "ba" (3) do not


def schema(profile):
    """One table for the prompt: hide lossless __raw columns, group fully blank columns."""
    blanks = {c['name']: c.get('blank', 0) for c in profile['columns']}
    columns, empty = [], []
    for c in profile['columns']:
        name = c['name']
        if name.endswith(RAW_SUFFIX) and blanks.get(name[:-len(RAW_SUFFIX)]) == blanks[name]:
            continue                                  # parsing lost nothing: the original text adds nothing
        if profile['rows'] and blanks[name] >= profile['rows']:
            empty.append(name)
            continue
        column = {k: v for k, v in c.items() if k != 'lookup'}
        raw = name + RAW_SUFFIX
        if raw in blanks and blanks[raw] == blanks[name]:      # its __raw column is hidden: do not point to it
            column['about'] = column.get('about', '').replace(f'; parsed from text, original in "{raw}"', '; parsed from text')
        columns.append(column)
    entry = {'table': profile['table'], 'rows': profile['rows'], 'source_files': profile['sources']}
    if profile.get('title'):
        entry['text_above_header'] = profile['title']
    if profile['dropped_rows']:
        entry['dropped_rows'] = profile['dropped_rows']
        if examples := {k: v for k, v in profile.get('dropped_examples', {}).items() if v}:
            entry['dropped_examples'] = examples
    if profile['exact_duplicate_rows']:
        entry['exact_duplicate_rows'] = profile['exact_duplicate_rows']
    entry['columns'] = columns
    if empty:
        entry['empty_columns'] = empty
    return entry


def build_catalog(business, rulebook, changed=()):
    """changed: rule lines of this set with no train match; shown after the documents (closest to the question)."""
    schemas = [schema(p) for p in business.profiles]
    schemas.sort(key=lambda t: t['table'] == 'calendar')          # shop tables first, shared calendar last
    catalog = {'notes': NOTES, 'schemas': schemas}
    if notes := data_notes(business):
        catalog['data_notes'] = notes
    if groups := label_groups(schemas):
        catalog['label_groups'] = groups
    catalog['documents'] = [{'name': 'README.md', 'text': business.readme}, {'name': 'rulebook.md', 'text': rulebook}]
    if getattr(business, 'unreadable', None):                      # data the tables do not hold
        catalog['unreadable_files'] = {'note': UNREADABLE, 'files': list(business.unreadable)}
    if changed:
        catalog['rulebook_changes'] = list(changed)
    return catalog


def _padded(text):
    return ' ' + text + ' '


def label_groups(schemas):
    """Status/payment labels grouped by their words (a column naming 2+ concepts of one kind); the rest: 'not matched'."""
    out = []
    for table in schemas:
        for column in table['columns']:
            values = [v for v, _ in column.get('all_values', []) if isinstance(v, str)]
            for kind, concepts in LABEL_WORDS.items():
                hit = {c: found for c, words in concepts.items()
                       if (found := [v for v in values if any(_padded(w) in _padded(norm(v)) for w in words.split('|'))])}
                if len(hit) >= 2:
                    if other := [v for v in values if not any(v in found for found in hit.values())]:
                        hit['not matched'] = other
                    out.append({'table': table['table'], 'column': column['name'], 'kind': kind, 'labels': hit})
    return out


def _names_something(words):
    """A phrase with at least two words of letters, one of them not an everyday question word."""
    alpha = [w for w in words if not any(ch.isdigit() for ch in w)]
    return len(alpha) >= 2 and any(w not in FUNCTION_WORDS for w in alpha)


def lookup(question, business):
    """Where names and values mentioned in the question occur (accent/case/punctuation-insensitive, word
    boundaries): a stored value mentioned in the question, or a 2-4 word phrase of the question inside a value."""
    q = norm(question)
    if not q:
        return []
    words, accented = q.split(), norm(question, accents=True).split()     # same tokens, with and without accents
    after_title = lambda i: i > 0 and len(accented) == len(words) and accented[i - 1] in HONORIFICS
    phrases = {p for n in (4, 3, 2) for i in range(len(words) - n + 1) if len(p := ' '.join(words[i:i + n])) >= 6
               and (_names_something(words[i:i + n]) or after_title(i))}
    found = {}
    for profile in business.profiles:
        for column, entries in profile.get('lookup', {}).items():
            if column.endswith((RAW_SUFFIX, UNIT_SUFFIX)) or column == SOURCE_COL:
                continue                                      # original text of parsed cells, units, origin files
            for value, count in entries:
                v = norm(value)
                if len(v) < 3 or v.replace(' ', '').isdigit():
                    continue
                # A one-word value must be distinctive (long, or a code with a digit): "bao" in "bao nhieu" is not a match.
                if ' ' not in v and len(v) < 5 and not any(ch.isdigit() for ch in v):
                    continue
                key = (profile['table'], column, value)
                if _padded(v) in _padded(q):
                    found[key] = (len(v), 'mentioned in question', count)
                elif hit := max((p for p in phrases if _padded(p) in _padded(v)), key=lambda p: (len(p), p), default=None):
                    found.setdefault(key, (len(hit) - 0.5, f'contains "{hit}"', count))
    named = {}
    for (table, column, value), (_, why, _) in found.items():
        if why == 'mentioned in question':
            named.setdefault((table, column), []).append(_padded(norm(value)))
    sibling = lambda k, why: any(_padded(why[len('contains "'):-1]) in v for v in named.get(k[:2], []))
    found = {k: f for k, f in found.items() if f[1] == 'mentioned in question' or not sibling(k, f[1])}   # a partial
    # phrase inside a value the question names in that column only brings its siblings (Nước ép cam -> dưa hấu)
    out, per_phrase = [], {}
    ranked = sorted(found.items(), key=lambda kv: (kv[1][1] != 'mentioned in question', -kv[1][0], kv[0]))
    for (table, column, value), (_, why, count) in ranked:          # values the question names come first
        if why != 'mentioned in question':
            per_phrase[why] = per_phrase.get(why, 0) + 1
            if per_phrase[why] > MAX_PER_PHRASE:
                continue
        out.append({'table': table, 'column': column, 'value': value, 'rows': int(count), 'match': why})
        if len(out) >= MAX_MATCHES:
            break
    return out
