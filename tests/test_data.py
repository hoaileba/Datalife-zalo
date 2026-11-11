"""Reader and profile (data.py, grids.py, values.py): format fixes only, sandbox dtypes, catalog."""
import datetime as dt

import numpy as np
import pandas as pd

from datamate.catalog import build_catalog, lookup, schema
from datamate.data import is_text, load_business, type_column, to_series
from datamate.values import parse_datetime, parse_number, parse_qty


def test_value_parsers():
    assert parse_number('1.234.567 đ') == 1234567 and parse_number('19tr990') == 19990000 and parse_number('120k') == 120000
    assert parse_number('1,5') == 1.5 and parse_number('(5.000)') == -5000 and parse_number('abc') is None
    assert parse_number('1,047tr') == 1047000 and parse_number('2,35 triệu') == 2350000 and parse_number('1,1k') == 1100   # exact
    assert parse_qty('2 chai') == (2, 'chai') and parse_qty('1 thùng = 24 lon') == (1, 'thùng')
    assert parse_datetime('03/04/2025') == dt.datetime(2025, 4, 3) and parse_datetime('ngày 3 tháng 4 năm 2025') == dt.datetime(2025, 4, 3)
    assert parse_datetime(45689) == dt.datetime(2025, 2, 1) and parse_datetime('5/4', 2026) == dt.datetime(2026, 4, 5)


def test_column_typing_and_dtypes():
    kind, values, _ = type_column(['0012', '0013'], ['', ''])
    assert kind == 'text'                                            # leading zeros: a code, not a number
    assert to_series('number', [1.0, 2.0]).dtype == np.int64 and to_series('number', [1.0, None]).dtype == np.float64
    assert is_text(to_series('text', ['a', None])) and str(to_series('date', [dt.datetime(2026, 1, 1), None]).dtype) == 'datetime64[ns]'


def test_business_tables_profiles_and_cache(split, tmp_path):
    b = load_business(split / 'data' / 'biz_1', split / 'calendar.csv', tmp_path / 'c')
    assert list(b.tables) == ['ban_hang', 'calendar']
    df = b.tables['ban_hang']
    assert len(df) == 4                                              # title, blank and total rows dropped
    assert df['Thành tiền'].dtype == np.int64 and str(df['Ngày'].dtype) == 'datetime64[ns]'
    profile = b.profiles[0]
    assert profile['exact_duplicate_rows'] == 1 and profile['dropped_rows'] == {'blank': 1, 'total': 1}
    status = next(c for c in profile['columns'] if c['name'] == 'Trạng thái')
    assert status['all_values'] == [['Hoàn thành', 3], ['Đã hủy', 1]]
    again = load_business(split / 'data' / 'biz_1', split / 'calendar.csv', tmp_path / 'c')
    assert again.tables['ban_hang'].equals(df)                       # served from the cache


def test_catalog_hides_lossless_raw_and_groups_empty_columns():
    profile = {'table': 't', 'rows': 5, 'sources': ['t.csv'], 'dropped_rows': {}, 'exact_duplicate_rows': 0, 'columns': [
        {'name': 'Ngày', 'blank': 0}, {'name': 'Ngày__raw', 'blank': 0}, {'name': 'Tiền', 'blank': 2},
        {'name': 'Tiền__raw'}, {'name': 'Ghi chú', 'blank': 5}]}
    table = schema(profile)
    assert [c['name'] for c in table['columns']] == ['Ngày', 'Tiền', 'Tiền__raw'] and table['empty_columns'] == ['Ghi chú']


def test_catalog_prefix_and_lookup(split, tmp_path):
    b = load_business(split / 'data' / 'biz_1', split / 'calendar.csv')
    catalog = build_catalog(b, 'RULES')
    assert [d['name'] for d in catalog['documents']] == ['README.md', 'rulebook.md'] and catalog['schemas'][-1]['table'] == 'calendar'
    hits = lookup('khach nguyen van an mua gi', b)
    assert hits[0]['value'] == 'Nguyễn Văn An' and hits[0]['match'] == 'mentioned in question'
    assert not lookup('bao nhieu don', b)                            # everyday words never match


def test_hidden_raw_column_is_not_referenced():
    profile = {'table': 't', 'rows': 2, 'sources': [], 'dropped_rows': {}, 'exact_duplicate_rows': 0, 'columns': [
        {'name': 'Tiền', 'about': 'number; parsed from text, original in "Tiền__raw"'}, {'name': 'Tiền__raw'}]}
    assert schema(profile)['columns'] == [{'name': 'Tiền', 'about': 'number; parsed from text'}]


def test_calendar_weekday_meaning_is_stated(split):
    b = load_business(split / 'data' / 'biz_1', split / 'calendar.csv')
    weekday = next(c for c in b.profiles[-1]['columns'] if c['name'] == 'weekday')
    assert '1=Monday' in weekday['about']



def test_total_rows_need_a_total_label():
    from datamate.data import body_rows
    rows = [['Khách / hàng', 'Số', 'Tiền', 'Ghi chú'],
            ['Công tắc 1 chiều', 45658.0, '35.000đ', 'x'],         # a product starting with "Công": kept
            ['Tống Thu', 5, 1200000, 'x'],                          # the surname Tống: kept
            ['Tong Ngoc Chi', 1, 5, 'x'],                           # the surname Tống without accents: kept
            ['Tổng hợp hải sản', 3, 4, 'x'], ['TC-01', 2, 5, 'x'],     # a full row named like a total; "TC-01" a code
            ['Tổng ngày 01/01', None, '35.000đ'], ['Tổng cộng (VNĐ)', 8, 1500005], ['Tổng số lượng', 8, None],
            ['Cộng tiền hàng', 8, 1500005], ['TỔNG QUÝ I', 8, 1], ['Tong cong', 8, 1], ['Total', 8, 1],
            ['Tong cong (VNĐ)', 8, 1], ['TC', 8, 1]]
    data, dropped, _ = body_rows(rows, 0)
    assert [rows[i][0] for i in data] == ['Công tắc 1 chiều', 'Tống Thu', 'Tong Ngoc Chi', 'Tổng hợp hải sản', 'TC-01']
    assert dropped == {'total': 9}


def test_totals_found_by_arithmetic_whatever_the_label():
    from datamate.data import body_rows
    head = [['Mã', 'Ngày', 'Hàng', 'SL', 'Tiền']]
    day1 = [['HD1', '01/05/2025', 'Bia', 2, 20000], ['HD2', '01/05/2025', 'Nước', 1, 5000]]
    day2 = [['HD3', '02/05/2025', 'Bia', 1, 10000], ['HD4', '02/05/2025', 'Bánh', 3, 30000], ['HD5', '02/05/2025', 'Kẹo', 1, 1000]]
    rows = head + day1 + [['Cộng ngày', '01/05/2025', None, 3, 25000]] + day2 + \
        [['Subtotal', None, None, 5, 41000], ['Grand Total', None, None, 8, 66000], [], ['Người lập biểu', None, 'Kế toán trưởng'],
         ['(Ký, họ tên)']]
    data, dropped, extra = body_rows(rows, 0)
    assert [rows[i][0] for i in data] == ['HD1', 'HD2', 'HD3', 'HD4', 'HD5']
    assert dropped['total_by_sum'] == 3 and dropped['footer'] == 1 and dropped['note'] == 1
    top = head + [[None, None, None, 8, 66000]] + day1 + day2                                  # a total printed first
    assert body_rows(top, 0)[0] == list(range(2, 7))
    full = [['Hàng', 'SL', 'Tiền'], ['Bia', 2, 20000], ['Nước', 1, 5000], ['Bánh', 3, 25000]]   # Bánh is a sum by chance
    assert body_rows(full, 0)[0] == [1, 2, 3]                       # a full row needs a total label to be checked


def test_section_rows_become_a_column(tmp_path):
    text = 'Mã,Hàng,SL,Tiền\nNhóm: Bia,,,\nB1,Bia lon,2,20000\nB2,Bia chai,1,9000\nNhóm: Bánh,,,\nK1,Bánh quy,3,30000\n'
    tables = _write(tmp_path / 's', {'sp.csv': text})
    frame, meta = tables['sp']
    assert frame['__section'].tolist() == ['Nhóm: Bia', 'Nhóm: Bia', 'Nhóm: Bánh'] and meta['dropped_rows'] == {'section': 2}


def test_reader_choices_follow_the_column(tmp_path):
    text = ('Ngày,Cân nặng,Giá\n12/25/2025,"1,250","1.500.000"\n01/02/2026,"0,5","25.000"\n'
            '01/03/2026,"2,125","300.000"\n01/04/2026,"1,5","50.000"\n')
    frame, meta = _write(tmp_path / 'u', {'us.csv': text})['us']
    assert [str(d.date()) for d in frame['Ngày']] == ['2025-12-25', '2026-01-02', '2026-01-03', '2026-01-04']
    assert frame['Cân nặng'].tolist() == [1.25, 0.5, 2.125, 1.5] and frame['Giá'].tolist() == [1500000, 25000, 300000, 50000]
    from datamate.columns import decimal_mark
    assert decimal_mark(['1.250.000', '35,000']) is None and decimal_mark(['1.000', '2.000', '1.500', '0.5']) is None
    assert 'month/day/year' in meta['notes']['Ngày'] and 'decimal mark' in meta['notes']['Cân nặng']


def test_one_cell_rows_inside_a_list_are_records(tmp_path):
    text = 'Tên NCC,Điện thoại,Địa chỉ,Ghi chú\nVinamilk,0283,Q7,Giao T2\nĐại lý bia,,,\nTạp hóa Ba,0909,,\nNPP Kinh Đô,,,\n'
    frame, meta = _write(tmp_path / 'n', {'ncc.csv': text})['ncc']
    assert len(frame) == 4 and not meta['dropped_rows']


def test_fill_down_never_runs_on_a_list_of_records(tmp_path):
    text = 'Mã KH,Tên,Điện thoại,Email\nKH1,An,0901,a@x\nKH2,Bình,,\nKH3,Chi,0903,c@x\nKH4,Dũng,,\nKH5,Em,0905,e@x\n'
    frame, meta = _write(tmp_path / 'c', {'kh.csv': text})['kh']
    assert frame['Điện thoại'].isna().sum() == 2 and '__group_start' not in frame


def test_two_row_header_and_sheets_with_other_meaning(tmp_path):
    from datamate.layout import partition_key, sub_header
    rows = [['Ngày', 'Bán', None, 'Trả lại', None], [None, 'SL', 'Tiền', 'SL', 'Tiền'], ['01/05/2025', 2, 20000, 1, 10000]]
    assert sub_header(rows, 0) == ['Ngày', 'Bán / SL', 'Bán / Tiền', 'Trả lại / SL', 'Trả lại / Tiền']
    assert partition_key('SoKho.xlsx:Nhập kho') != partition_key('SoKho.xlsx:Xuất kho')
    assert partition_key('SoBanHang.xlsx:T1') == partition_key('SoBanHang.xlsx:Tháng 2') == partition_key('SoBanHang.xlsx:Sheet1')


def _write(folder, files):
    folder.mkdir(exist_ok=True)
    for f, text in files.items():
        (folder / f).write_text(text, encoding='utf-8')
    from datamate.data import build_tables
    return {name: (frame, meta) for name, frame, meta in build_tables(folder)}


def test_period_partitions_merge_under_one_name(tmp_path):
    row = 'Ngày,Món,Tiền\n01/01/2025,Trà,"10.000"\n'
    tables = _write(tmp_path / 'a', {'BanHang_T10_2025.csv': row, 'BanHang_T1_2026.csv': row, 'Mat10.csv': row.replace('Món', 'Khoá')})
    assert set(tables) == {'ban_hang', 'mat'} and len(tables['ban_hang'][0]) == 2 and '__source' in tables['ban_hang'][0]
    tables = _write(tmp_path / 'b', {'T1.csv': row, 'T2.csv': row, 'T3.csv': row})                    # named only by period
    assert set(tables) == {'data'} and len(tables['data'][0]) == 3
    tables = _write(tmp_path / 'c', {'DoanhThu_Q1_2025.csv': row, 'DoanhThu_Q2_2025.csv': row, 'BanHang_Jan2025.csv': row,
                                     'BanHang_Feb2025.csv': row})
    assert {n: len(f) for n, (f, _) in tables.items()} == {'ban_hang': 2, 'doanh_thu': 2}
    tables = _write(tmp_path / 'd', {'DienMay.csv': row, 'Danh_sach_may.csv': row.replace('Món', 'Máy')})
    assert set(tables) == {'dien_may', 'danh_sach_may'}                                      # "máy" is not May


def test_partition_with_reordered_columns_joins_and_added_column_stays_apart(tmp_path):
    tables = _write(tmp_path / 'a', {'BanHang_T1.csv': 'Ngày,Món,Tiền\n01/01/2025,Trà,"10.000"\n',
                                     'BanHang_T2.csv': 'Món,Ngày,Tiền\nCà phê,01/02/2025,"20.000"\n',
                                     'BanHang_T3.csv': 'Ngày,Món,Tiền,Ghi chú\n01/03/2025,Bạc xỉu,"30.000",mang đi\n'})
    assert {n: len(f) for n, (f, _) in tables.items()} == {'ban_hang': 2, 'ban_hang_2': 1}
    frame, meta = tables['ban_hang']
    assert frame['Món'].tolist() == ['Trà', 'Cà phê'] and frame['Tiền'].tolist() == [10000, 20000]
    assert tables['ban_hang_2'][1]['sources'] == ['BanHang_T3.csv']                      # the catalog shows the split


def test_lookup_lists_never_join_a_fact_table():
    from datamate.layout import partition_groups
    sales, products = ['Ngày', 'Mã hàng', 'Tên hàng', 'SL', 'Đơn giá'], ['Mã hàng', 'Tên hàng', 'Đơn giá']
    for a, b in [('BaoCao.xlsx:Sheet1', 'BaoCao.xlsx:Sheet2'), ('BaoCao_2025.xlsx:Sheet1', 'BaoCao_2025.xlsx:Sheet2'),
                 ('DuLieu_T10.xlsx:Sheet1', 'DuLieu_T10.xlsx:Sheet2'), ('DonHang.csv', 'DonHang_2.csv'),
                 ('DonHang_2025.csv', 'DonHang_2025_2.csv'), ('BanHang_T1_2025.csv', 'BanHang_2025.csv')]:
        assert partition_groups({a: {'labels': sales}, b: {'labels': products}}) == [[a], [b]]


def test_headers_equal_after_folding_keep_their_columns(tmp_path):
    tables = _write(tmp_path / 'a', {'X_T1.csv': 'Ngày,Giá,GIÁ\n01/01/2025,1,2\n', 'X_T2.csv': 'GIÁ,Ngày,Giá\n4,02/01/2025,3\n',
                                     'X_T3.csv': 'Ngày,Giá,Tiền\n03/01/2025,5,6\n'})
    frame = tables['x'][0]
    assert frame['Giá'].tolist() == [1, 3] and frame['GIÁ'].tolist() == [2, 4]       # n-th "gia" to n-th "gia"
    assert len(tables['x_2'][0]) == 1                                                  # one "gia" only: another column set



def test_unreadable_files_are_skipped_and_listed(tmp_path):
    import sqlite3
    from datamate.data import load_business
    folder = tmp_path / 'biz'
    folder.mkdir()
    (folder / 'ban_hang.csv').write_bytes('Ngày,Tên,Tiền\n01/03/2025,Bánh\rmì,5\n02/03/2025,B,"'.encode() + b'x' * 200000 + b'"\n')
    (folder / 'hong.xlsx').write_bytes(b'not a zip')                                   # corrupt: skipped, listed
    (folder / '~$ban_hang.xlsx').write_bytes(b'lock')                                  # editor leftovers: ignored
    (folder / '._ban_hang.csv').write_bytes(b'\x00\x05')
    (folder / 'readme.md').write_bytes('# Quán\n'.encode('cp1258'))                   # not UTF-8, lower case
    (folder / '2025').mkdir()                                                          # listed, not read
    with sqlite3.connect(folder / 'db.sqlite') as con:
        con.execute('CREATE TABLE "a""b" (x)')                                          # quote in the name
        con.execute('INSERT INTO "a""b" VALUES (1)')
        con.execute('CREATE VIEW broken AS SELECT * FROM gone_table')                   # one bad object only
    (tmp_path / 'cal.csv').write_text('date,weekday\n2025-03-01,6\n', encoding='utf-8')
    b = load_business(folder, tmp_path / 'cal.csv', None)
    assert b.tables['ban_hang']['Tên'].tolist()[0] == 'Bánh mì' and len(b.tables['ban_hang']) == 2   # lone CR, huge cell
    assert b.tables['a_b']['x'].tolist() == [1] and b.readme == '# Quán\n'
    assert [u.split(':')[0] for u in b.unreadable] == ['2025/', 'db.sqlite', 'hong.xlsx']
    cache = tmp_path / 'c'
    load_business(folder, tmp_path / 'cal.csv', cache)
    next(cache.iterdir()).write_bytes(b'truncated')                                  # damaged cache: rebuilt
    assert load_business(folder, tmp_path / 'cal.csv', cache).tables['a_b']['x'].tolist() == [1]


def test_load_failure_is_remembered_and_cache_falls_back(tmp_path):
    from datamate.runner import Businesses, writable_dir
    locked = tmp_path / 'ro'
    locked.mkdir()
    locked.chmod(0o555)
    try:
        assert writable_dir(locked / 'cache', tmp_path / 'out' / 'cache') == tmp_path / 'out' / 'cache'
    finally:
        locked.chmod(0o755)
    calls = []
    businesses = Businesses(tmp_path, '', tmp_path / 'c')
    import datamate.runner as runner
    original, runner.load_business = runner.load_business, lambda *a: calls.append(a) or 1 / 0
    try:
        for _ in range(2):
            try:
                businesses.get('missing')
            except ZeroDivisionError:
                pass
    finally:
        runner.load_business = original
    assert len(calls) == 1




def test_lookup_ignores_helper_columns_and_everyday_phrases():
    from datamate.data import Business
    b = Business('x', '', profiles=[{'table': 'kh', 'lookup': {
        'Tên khách': [('La Bảo Hùng', 3), ('Cà phê sữa đá', 9)], 'Ngày__raw': [('1 thg 3 2026', 5)],
        'SL__unit': [('miếng', 4)], 'Đơn vị': [('miếng', 4)]}}])
    assert not lookup('thang 3/2026 ti le don bi huy la bao nhieu', b)        # "la bao", "3 2026" name nothing
    hits = lookup('bán được bao nhiêu miếng cà phê sữa', b)
    assert [h['value'] for h in hits] == ['miếng', 'Cà phê sữa đá']                # named value first, no __unit copy
    assert hits[1]['match'] == 'contains "ca phe sua"'


def test_lookup_names_after_honorifics_and_no_siblings():
    from datamate.data import Business
    b = Business('x', '', profiles=[{'table': 'kh', 'lookup': {
        'Khách': [('Trần Thị Mai Lan', 2), ('Lê Bảo Ngọc', 1)],
        'Món': [('Nước ép cam (M)', 5), ('Nước ép dưa hấu (M)', 4), ('Hapacol hộp 24 gói', 3)]}}])
    assert [h['value'] for h in lookup('chị Mai Lan còn nợ bao nhiêu', b)] == ['Trần Thị Mai Lan']   # a name of everyday words
    assert [h['value'] for h in lookup('tháng 3 bán được bao nhiêu ly nước ép cam (M)', b)] == ['Nước ép cam (M)']
    assert not lookup('bán được bao nhiêu hộp 24 gói', b)                                           # packaging names nothing
    assert not lookup('tỉ lệ đơn bị huỷ là bao nhiêu', b)
    b.profiles[0]['lookup']['Khách'] += [('Khách hàng lẻ', 9), ('La Bảo Hùng', 1), ('Ba Ngày Shop', 1)]
    for q in ('tháng này có khách hàng nào nợ', 'doanh thu của em là bao nhiêu', 'ba ngày gần nhất bán bao nhiêu'):
        assert not lookup(q, b), q                                       # có / em / ba (three) are not titles

def test_catalog_explains_unreadable_files(split):
    from datamate.catalog import UNREADABLE
    b = load_business(split / 'data' / 'biz_1', split / 'calendar.csv')
    assert 'unreadable_files' not in build_catalog(b, 'R')
    b.unreadable.append('x.xlsx: unreadable, ZipError')
    assert build_catalog(b, 'R')['unreadable_files'] == {'note': UNREADABLE, 'files': ['x.xlsx: unreadable, ZipError']}



def _noisy_shop():
    import pandas as pd
    from datamate.data import Business
    codes = [f'SP{i:03d}' for i in range(30)]
    names = [f'Nước ngọt số {i}' for i in range(30)]
    items = pd.DataFrame({'Mã hàng': codes, 'Tên hàng': names, 'Thành phố': [f'Thành phố {i}' for i in range(30)]})
    statuses = ['Hoàn thành', 'Đã hủy', 'Đang giao', 'Trả hàng', 'Chờ xử lý']
    customers = ['Doãn Dũng Thanh', 'Đoàn Dũng Thanh', 'Lê Văn Hà', 'Lê Văn Hạ', 'Trần Mai']      # five different people
    n = 150
    lines = pd.DataFrame({'Mã đơn': [f'D{i // 2}' for i in range(n)],                    # two lines per order
                          'Mã hàng': [codes[i % 30] for i in range(n - 5)] + ['SP999'] * 5,     # SP999: not in the master
                          'Tên hàng': [names[i % 30] if i % 7 else names[i % 30].upper() for i in range(n)],
                          'ĐVT': ['lốc' if (i // 30) % 2 else 'lon' for i in range(n)],             # each item in both
                          'Trạng thái': [statuses[i % 5] for i in range(n)],
                          'Khách': [customers[i % 5] for i in range(n)],
                          'Thành phố': [f'Thành phố {i % 30}' for i in range(n)]})
    readme = 'Quy đổi: ' + '; '.join(f'{x}: 1 lốc = 6 lon' for x in names)
    return Business('x', readme, tables={'hang_hoa': items, 'ban_hang': lines, 'calendar': pd.DataFrame()})


def test_data_notes_joins_against_the_master_and_never_on_non_keys():
    import pandas as pd
    from datamate.notes import data_notes
    joins = data_notes(_noisy_shop())['joins']
    by_key = {j['key']: j for j in joins}
    assert by_key['Mã hàng']['master'] == 'hang_hoa.Mã hàng'
    assert by_key['Mã hàng']['others'] == {'ban_hang.Mã hàng': '1 of 31 values (5 rows) not in the master'}
    debt = pd.DataFrame({'Mã đơn': [f'D{i}' for i in range(20)], 'Còn nợ': range(20)})       # a partial table
    shop = _noisy_shop()
    shop.tables['cong_no'] = debt
    assert 'Mã đơn' not in {j['key'] for j in data_notes(shop).get('joins', [])}          # never "most orders do not join"
    assert 'Trạng thái' not in by_key and 'Khách' not in by_key


def test_data_notes_variants_are_case_spaces_or_missing_accents_only():
    from datamate.notes import data_notes
    notes = data_notes(_noisy_shop())
    variants = {v['column']: v for v in notes['spelling_variants']}
    assert variants['ban_hang.Tên hàng']['values_written_several_ways'] == 22                # NƯỚC NGỌT = Nước ngọt
    assert 'ban_hang.Khách' not in variants                     # Doãn/Đoàn, Hà/Hạ: a tone mark makes another person
    assert all(not c.startswith('hang_hoa.') for c in variants)  # a master list (unique per row) is not reported


def test_data_notes_units_are_words_counted_after_numbers():
    from datamate.notes import data_notes
    units = data_notes(_noisy_shop())['units']
    assert {(u['item'], u['unit']) for u in units} == {('Tên hàng', 'ĐVT')}       # README: 1 lốc = 6 lon
    assert all(u['unit'] != 'Trạng thái' and u['item'] not in ('Khách', 'Trạng thái') for u in units)


def test_data_notes_are_stable_and_never_fatal():
    import pandas as pd
    from datamate.data import Business
    from datamate.notes import data_notes
    shop = _noisy_shop()
    shuffled = Business('x', shop.readme, tables={k: shop.tables[k] for k in reversed(list(shop.tables))})
    shuffled.tables['ban_hang'] = shuffled.tables['ban_hang'].sample(frac=1, random_state=1).reset_index(drop=True)
    assert data_notes(shuffled) == data_notes(shop)
    assert data_notes(Business('z', '', tables={'t': pd.DataFrame({'a': ['x']})})) is None


def test_data_notes_failure_drops_only_the_notes(monkeypatch):
    import datamate.notes as notes
    from datamate.catalog import build_catalog
    shop = _noisy_shop()
    shop.profiles = []
    monkeypatch.setattr(notes, '_joins', lambda *a: 1 / 0)
    catalog = build_catalog(shop, 'R')
    assert 'data_notes' not in catalog and catalog['documents'][1]['text'] == 'R'


def test_header_title_rows_years_bools_and_dateless_sheets(tmp_path):
    from datamate.grids import find_header
    from datamate.layout import partition_groups
    from datamate.values import parse_datetime
    rows = [['Kỳ báo cáo:', 'Năm 2025', None, 'Đơn vị tính:', 'VNĐ'], [None] * 5, ['Mã', 'Tên', 'Đơn vị', 'Giá', None],
            ['A1', 'Bia', 'lon', 10000, None], ['A2', 'Nước', 'chai', 8000, None]]
    assert find_header(rows, False) == (2, None)                    # a wide title row is not the header
    assert parse_datetime('24/11/84').year == 1984 and parse_datetime('01/02/25').year == 2025
    frame, _ = _write(tmp_path / 'b', {'sp.csv': 'Mã,Kê đơn\nA,True\nB,False\n'})['sp']
    assert frame['Kê đơn'].dtype == bool
    grid = type('G', (), {'rows': [['Mã', 'SL'], ['A', 1]]})
    parsed = {f'Kho.xlsx:{s}': {'labels': ['Mã', 'SL'], 'grid': grid, 'data': [1]} for s in ('Đầu kỳ', 'Cuối kỳ')}
    assert partition_groups(parsed) == [['Kho.xlsx:Đầu kỳ'], ['Kho.xlsx:Cuối kỳ']]   # no dates: kept apart, no crash
