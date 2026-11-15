"""File layouts real shops use that gen.render does not make, applied to a rendered shop (gen.world, before renames):

  monthly_files : a workbook of month sheets -> one file per month (`<stem>_T01_2025.xlsx` ...), each one sheet
  master_book   : several small list files (products, customers, units, prices, suppliers) -> one workbook, a sheet each

relayout(src, dst, calendar, rng, p_month, p_master) -> info. The README is updated to the new file names; the copy is
read back with datamate.data.load_business and must give the same tables (columns and rows) as the original, else
the original is kept (info['kept_original']).
"""
from __future__ import annotations

import re
import shutil
from collections import Counter
from pathlib import Path

from gen.shopio import Sheet, ShopFile, read_shop, write_shop

PERIOD = re.compile(r'(?i)^(?:T|Thang |Tháng |Th)?(\d{1,2})(?:[ ._\-](\d{4}))?$')
MASTER_WORDS = ('sanpham', 'hanghoa', 'khachhang', 'donvi', 'quydoi', 'danhmuc', 'nhacungcap', 'banggia', 'items', 'uom',
                'nhanvien', 'customers', 'products', 'chinhanh')
MASTER_BOOKS = ('DanhMuc.xlsx', 'Danh_muc.xlsx', 'DanhSach.xlsx', 'MasterData.xlsx', 'Danh muc chung.xlsx')


def _fold(s):
    from gen.industry_gen import _fold as f
    return re.sub(r'[^a-z]', '', f(s))


def monthly_candidates(files):
    return [f for f, sf in files.items() if sf.kind == 'xlsx' and len(sf.sheets) >= 3
            and all(s.name and PERIOD.match(s.name.strip()) for s in sf.sheets)]


def explode_months(files, f):
    """One file per month sheet of workbook f: {new name: ShopFile}, in sheet order."""
    sf = files[f]
    stem = Path(f).stem
    year = re.search(r'(20\d{2})$', stem)
    out = {}
    for s in sf.sheets:
        m = PERIOD.match(s.name.strip())
        mm, yy = int(m.group(1)), m.group(2) or (year.group(1) if year else None)
        base = re.sub(r'[_\- ]?20\d{2}$', '', stem) if yy and year else stem
        name = f'{base}_T{mm:02d}_{yy}.xlsx' if yy else f'{base}_T{mm:02d}.xlsx'
        out[name] = ShopFile(name, 'xlsx', [Sheet('Sheet1', s.rows)])
    return out


def master_candidates(files):
    out = []
    for f, sf in files.items():
        if sf.kind == 'sqlite' or len(sf.sheets) != 1:
            continue
        key = _fold(Path(f).stem)
        if any(w in key for w in MASTER_WORDS) and len(sf.sheets[0].rows) <= 3000:
            out.append(f)
    return out


def _readme_monthly(text, f, news):
    shown = ', '.join(f'`{n}`' for n in news[:2]) + '…'
    lines = []
    for ln in text.split('\n'):
        if re.match(rf'^- `{re.escape(f)}` \(xlsx\)', ln):
            lines += [f'- `{n}` (xlsx)' for n in news]
            continue
        if ln.startswith('## Cột trong') and f'`{f}`' in ln:
            ln = re.sub(r', sheet `[^`]+`$', '', ln.replace(f'`{f}`', f'`{news[0]}`'))
        else:
            ln = ln.replace(f'`{f}`', shown)
        lines.append(ln)
    text = '\n'.join(lines)
    text = text.replace('chia mỗi tháng một sheet, tên sheet ghi tháng và năm', 'tách mỗi tháng một file, tên file ghi tháng và năm')
    return text.replace('mỗi tháng một sheet', 'mỗi tháng một file')


def _readme_master(text, members, book):
    lines, added = [], False
    for ln in text.split('\n'):
        m = re.match(r'^- `([^`]+)` \((?:csv|xlsx)\)', ln)
        if m and m.group(1) in members:
            if not added:
                lines.append(f'- `{book}` (xlsx)')
                added = True
            continue
        h = re.match(r'^## Cột trong `([^`]+)`(?:, sheet `[^`]+`)?\s*$', ln)
        if h and h.group(1) in members:
            ln = f'## Cột trong `{book}`, sheet `{members[h.group(1)]}`'
        else:
            for old, sheet in members.items():
                ln = ln.replace(f'`{old}`', f'sheet `{sheet}` của `{book}`')
        lines.append(ln)
    text = '\n'.join(lines)
    note = (f'Các danh sách {", ".join(f"`{s}`" for s in members.values())} nằm chung file `{book}`, mỗi danh sách một sheet.')
    return re.sub(r'(\n## File\n)', '\n' + note + r'\n\1', text, count=1)


def _signature(business):
    return Counter((tuple(sorted(map(str, df.columns))), len(df)) for t, df in business.tables.items() if t != 'calendar')


def relayout(src: Path, dst: Path, calendar: Path, rng, p_month=0.35, p_master=0.3):
    from datamate.data import load_business
    files = read_shop(src)
    readme = (src / 'README.md').read_text(encoding='utf-8') if (src / 'README.md').exists() else ''
    info = {'monthly': [], 'master': None, 'kept_original': False}
    new = dict(files)
    for f in monthly_candidates(files):
        if rng.random() < p_month:
            parts = explode_months(files, f)
            if set(parts) & set(new):
                continue
            del new[f]
            new.update(parts)
            readme = _readme_monthly(readme, f, list(parts))
            info['monthly'].append(f)
    cands = master_candidates(new)
    if len(cands) >= 2 and rng.random() < p_master:
        book = MASTER_BOOKS[int(rng.integers(len(MASTER_BOOKS)))]
        if book not in new:
            members = {}
            sheets = []
            for f in cands:
                sheet = Path(f).stem[:31]
                members[f] = sheet
                sheets.append(Sheet(sheet, new.pop(f).sheets[0].rows))
            new[book] = ShopFile(book, 'xlsx', sheets)
            readme = _readme_master(readme, members, book)
            info['master'] = {'book': book, 'members': members}
    if not info['monthly'] and not info['master']:
        return info
    tmp = dst.with_name(dst.name + '_relayout')
    if tmp.exists():
        shutil.rmtree(tmp)
    write_shop(new, tmp)
    (tmp / 'README.md').write_text(readme, encoding='utf-8')
    try:
        ok = (not load_business(tmp, calendar, None).unreadable
              and _signature(load_business(tmp, calendar, None)) == _signature(load_business(src, calendar, None)))
    except Exception:              # noqa: BLE001
        ok = False
    if not ok:
        shutil.rmtree(tmp)
        return {'monthly': [], 'master': None, 'kept_original': True}
    if dst.exists():
        shutil.rmtree(dst)
    tmp.rename(dst)
    return info
