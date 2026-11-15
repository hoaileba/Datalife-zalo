"""README.md of a rendered shop, in the train template:

# Dữ liệu <id> / intro / ## File / (## Bảng) / ## Cột trong `file` / ## Quy ước (always "Dữ liệu có đến hết dd/mm/yyyy")

Three verbosity levels (Noise.verbosity): full (every file's columns), partial (sales files only), brief (no column
dictionary). Conventions are kept at every level: they carry meaning the files alone do not (returns written as
negative lines, service fee lines, unit conversions when there is no conversion table...).
"""
from __future__ import annotations

from pathlib import Path

from .pools import DOC, DOC_MASTER, FILLER_DOC


def _ref(name, p):
    return f'`{name}`' if p.get('code') else f'**{name}**'


def convention_text(kind, p):
    """One '## Quy ước' bullet (or a list of lines) from a convention kind and its parameters."""
    r = lambda k: _ref(p[k], p)
    if kind == 'raw':
        return p['text']
    if kind == 'debt_payments':
        return (f'**Công nợ**: mỗi lần khách trả tiền cho một đơn là một dòng, {r("pay")} là số tiền trả lần đó; '
                f'{r("total")} là số khách phải trả cho cả đơn.')
    if kind == 'debt_left':
        return f'**Còn nợ**: {r("col")} là số khách còn nợ của đơn, tính đến hết ngày cuối dữ liệu.'
    if kind == 'unit_cost':
        return f'**Giá vốn**: {r("col")} là giá vốn một đơn vị bán.'
    if kind == 'stock_end':
        return (f'**Tồn kho**: {r("col")} là tồn cuối ngày cuối có dữ liệu, theo đơn vị cơ bản; món làm tại chỗ, phí '
                f'không theo dõi tồn nên không có trong danh sách tồn.')
    if kind == 'stock_moves':
        return (f'**Tồn kho**: mỗi dòng `{p["col"]}` là tồn sau lần nhập/bán/trả đó, theo đơn vị cơ bản; tồn tại một '
                f'thời điểm là tồn ở dòng cuối của sản phẩm tính đến thời điểm đó.')
    if kind == 'lots':
        return ('**Lô, hạn dùng**: mỗi dòng nhập là một lô, số lô không trùng. Một dòng bán có thể lấy từ nhiều lô. '
                'Hàng khách trả về lại lô đã bán.')
    if kind == 'purchase_total':
        return (f'**Nhập hàng**: {r("cost")} là giá nhập một đơn vị, theo đơn vị nhập của dòng; {r("total")} là tổng '
                f'tiền của cả phiếu nhập.')
    if kind == 'purchase_line_total':
        return (f'**Nhập hàng**: {r("cost")} là giá nhập một đơn vị, theo đơn vị nhập của dòng; {r("total")} là tiền '
                f'nhập của cả dòng.')
    if kind == 'prices':
        return (f'**Giá bán**: {r("new")} (theo đơn vị cơ bản) áp dụng từ {r("date")} đến trước lần đổi giá sau của '
                f'cùng mặt hàng; dòng đầu mỗi mặt hàng là giá lúc bắt đầu dữ liệu ({r("old")} trống).')
    if kind == 'prices_h':
        return (f'**Giá bán**: `{p["price"]}` (theo đơn vị cơ bản) áp dụng từ `{p["date"]}` đến trước lần đổi giá sau '
                f'của cùng mặt hàng; dòng đầu mỗi mặt hàng là giá lúc bắt đầu dữ liệu.')
    if kind == 'drugs':
        return (f'**Thuốc**: {r("col")} đúng (TRUE/1) là thuốc kê đơn. Hoạt chất ghi không kèm hàm lượng (hàm lượng ở '
                f'tên hàng); nhiều chất nối bằng " + ".')
    if kind == 'expenses':
        return f'**Sổ chi phí**: các khoản chi vận hành theo tháng (tiền {r("col")}).'
    if kind == 'service_fee':
        return (f'**{p["name"]}**: một số đơn có thêm dòng hàng "{p["name"]}": phí phục vụ của đơn, tính theo tiền '
                f'món, đã ghi sẵn thành tiền.')
    if kind == 'returns_negative':
        return ('**Trả hàng**: hàng trả ghi số lượng âm, cùng mã đơn với đơn đã bán: đơn có dòng số lượng âm là đơn '
                'có trả hàng.')
    if kind == 'fill_down':
        cols = ', '.join(f'**{c}**' for c in p['cols'])
        return (f'**Dòng tiếp theo của một đơn**: từ dòng thứ hai của một đơn, các ô {cols} để trống: lấy theo dòng '
                f'đầu của đơn.')
    if kind == 'due':
        return (f'**Hạn thanh toán**: chỉ đơn bán nợ có hạn. {r("due")} là ngày khách phải trả hết đơn; {r("days")} là '
                f'số ngày được nợ, tính từ ngày đặt.')
    if kind == 'deliveries':
        return (f'**Giao hàng**: đơn giao tận nơi được giao 1–3 đợt ({r("trip")}); đơn khác khách tự chở, không có '
                f'trong sổ giao; đơn đặt mấy ngày cuối dữ liệu có thể chưa giao. {r("qty")} tính theo đơn vị cơ bản.')
    if kind == 'summary_sheet':
        return (f'**Tổng hợp theo ngày**: sheet `{p["sheet"]}` cộng sẵn theo ngày, tính **mọi đơn không huỷ, kể cả đơn '
                f'trả hàng** (cột **{p["amount"]}**); số liệu từng đơn, từng dòng hàng xem ở các sheet chi tiết.')
    if kind == 'units_table':
        where = p.get('where') or (f'bảng `{p["file"]}`' if p.get('table') else f'`{p["file"]}`')
        return f'**Quy đổi đơn vị**: số lượng ghi theo đơn vị của dòng, hệ số quy đổi ở {where}.'
    if kind == 'units_inline':
        if not p['items']:
            return '**Quy đổi đơn vị**: mọi mặt hàng bán theo đơn vị cơ bản, không có đơn vị lớn.'
        lines = ['**Quy đổi đơn vị**: số lượng ghi theo đơn vị của dòng:']
        lines += [f'  - {n}: 1 {u} = {f} {b}' for n, u, f, b in p['items']]
        return lines
    raise ValueError(kind)


def _is_master(keys):
    return 'order_id' not in keys and bool({'product_name', 'customer_name', 'customer_id'} & set(keys))


def _doc(key, header, master, overrides, fname):
    if (fname, header) in overrides:
        return overrides[(fname, header)]
    if key == 'filler':
        return FILLER_DOC.get(header)
    if master and key in DOC_MASTER:
        return DOC_MASTER[key]
    return DOC.get(key)


def column_sections(ctx, level):
    """'## Cột trong ...' blocks. Files whose sheets share a header are documented once; a workbook of different
    lists gets one block per sheet."""
    out = []
    for f in ctx.files:
        if not f.sheets or (level == 'partial' and f.role != 'sales'):
            continue
        seen = set()
        for s in f.sheets:
            sig = tuple(s.headers)
            if sig in seen:
                continue
            seen.add(sig)
            many = len({tuple(x.headers) for x in f.sheets}) > 1
            title = f'## Cột trong `{f.name}`, sheet `{s.name}`' if many else f'## Cột trong `{f.name}`'   # the train form
            master = _is_master(s.keys) and 'lot' not in s.keys
            rows = [(h, _doc(k, h, master, ctx.doc_override, f.name)) for h, k in zip(s.headers, s.keys)]
            body = [f'- **{h}**: {d}' for h, d in rows if d]
            if body:
                out.append('\n'.join([title] + body))
    return out


def readme_text(ctx) -> str:
    L, level = ctx.L, ctx.nz.verbosity
    bid = L.shop['business_id']
    end = L.shop['end']
    parts = [f'# Dữ liệu {bid}']
    intro = ctx.intro if level != 'brief' else ctx.intro[:1] + [x for x in ctx.intro[1:] if 'sheet' in x]
    parts += [x for x in intro if x]
    files = [f.name for f in ctx.files]
    parts.append('## File\n' + '\n'.join(f'- `{n}` ({n.rsplit(".", 1)[-1]})' for n in files))
    for kind, p in ctx.conventions:
        if kind == 'sqlite_tables':
            parts.append('## Bảng\n' + ', '.join(f'`{t}`' for t in p['tables']) + '\n\n' + p['join'])
    if level != 'brief':
        parts += column_sections(ctx, level)
    bullets = [f'- Dữ liệu có đến hết {end:%d/%m/%Y}.']
    for kind, p in ctx.conventions:
        if kind == 'sqlite_tables':
            continue
        t = convention_text(kind, p)
        if isinstance(t, list):
            bullets.append('- ' + t[0])
            bullets += t[1:]
        else:
            bullets.append('- ' + t)
    parts.append('## Quy ước\n' + '\n'.join(bullets))
    return '\n\n'.join(parts) + '\n'


def write_readme(ctx, out_dir: Path):
    text = readme_text(ctx)
    (Path(out_dir) / 'README.md').write_text(text, encoding='utf-8')
    return text
