"""Minimal dependency-free .xlsx writer (the dev env has neither openpyxl nor xlsxwriter).

write_xlsx(path, [(sheet_name, rows), ...]); a cell is None | str | bool | int | float | date | datetime.
Dates are written as Excel serials with a date (numFmt 14) or date-time (numFmt 22) style, so readers
(calamine, Excel) see real dates; a bare number that merely looks like a serial stays a number.
"""
from __future__ import annotations

import datetime as dt
import re
import zipfile
from xml.sax.saxutils import escape

EPOCH = dt.datetime(1899, 12, 30)
_BAD = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f]')
_SHEET_BAD = re.compile(r'[\[\]:*?/\\]')

CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/xl/workbook.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                 '<Override PartName="/xl/styles.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                 '<Override PartName="/xl/sharedStrings.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
                 '{sheets}</Types>')
SHEET_CT = ('<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
ROOT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
             'officeDocument" Target="xl/workbook.xml"/></Relationships>')
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
          '<xf numFmtId="22" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
          '</styleSheet>')


def col_letter(j: int) -> str:
    s = ''
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


def safe_sheet_name(name: str, used: set) -> str:
    base = _SHEET_BAD.sub('-', str(name))[:31] or 'Sheet'
    out, k = base, 2
    while out.lower() in used:
        out = f'{base[:28]}_{k}'
        k += 1
    used.add(out.lower())
    return out


def _serial(v) -> float:
    if isinstance(v, dt.datetime):
        return (v - EPOCH).total_seconds() / 86400.0
    return float((v - EPOCH.date()).days)


class _Strings:
    def __init__(self):
        self.index, self.items = {}, []

    def id(self, s: str) -> int:
        k = self.index.get(s)
        if k is None:
            k = self.index[s] = len(self.items)
            self.items.append(s)
        return k

    def xml(self) -> str:
        body = ''.join(f'<si><t xml:space="preserve">{escape(_BAD.sub("", s))}</t></si>' for s in self.items)
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(self.items)}" '
                f'uniqueCount="{len(self.items)}">{body}</sst>')


def _cell(ref: str, v, strings: _Strings):
    if v is None or (isinstance(v, float) and v != v):
        return ''
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
    if isinstance(v, dt.datetime):
        return f'<c r="{ref}" s="2"><v>{_serial(v)!r}</v></c>'
    if isinstance(v, dt.date):
        return f'<c r="{ref}" s="1"><v>{_serial(v)!r}</v></c>'
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        x = float(v)
        return f'<c r="{ref}"><v>{int(x) if x.is_integer() and abs(x) < 1e15 else repr(x)}</v></c>'
    if hasattr(v, 'item'):                       # numpy scalar
        return _cell(ref, v.item(), strings)
    s = str(v)
    if s == '':
        return ''
    return f'<c r="{ref}" t="s"><v>{strings.id(s)}</v></c>'


def _sheet_xml(rows, strings: _Strings) -> str:
    width = max((len(r) for r in rows), default=0)
    letters = [col_letter(j) for j in range(max(width, 1))]
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for i, r in enumerate(rows, 1):
        cells = ''.join(_cell(f'{letters[j]}{i}', v, strings) for j, v in enumerate(r))
        out.append(f'<row r="{i}">{cells}</row>')
    out.append('</sheetData></worksheet>')
    return ''.join(out)


class _Fixed:
    """Zip members with a fixed timestamp: same input, same bytes."""

    def __init__(self, zf):
        self.zf = zf

    def writestr(self, name, data):
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        self.zf.writestr(info, data)


def write_xlsx(path, sheets):
    """sheets: list of (name, rows). Sheet names are made Excel-safe and unique."""
    strings, used, names, bodies = _Strings(), set(), [], []
    for name, rows in sheets:
        names.append(safe_sheet_name(name, used))
        bodies.append(_sheet_xml(rows, strings))
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + ''.join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                    for i, n in enumerate(names, 1))
          + '</sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                      f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
            + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
              f'relationships/styles" Target="styles.xml"/>'
            + f'<Relationship Id="rId{len(names) + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
              f'relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        z = _Fixed(zf)
        z.writestr('[Content_Types].xml', CONTENT_TYPES.format(
            sheets=''.join(SHEET_CT.format(i=i) for i in range(1, len(names) + 1))))
        z.writestr('_rels/.rels', ROOT_RELS)
        z.writestr('xl/workbook.xml', wb)
        z.writestr('xl/_rels/workbook.xml.rels', rels)
        z.writestr('xl/styles.xml', STYLES)
        z.writestr('xl/sharedStrings.xml', strings.xml())
        for i, body in enumerate(bodies, 1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', body)
    return names
