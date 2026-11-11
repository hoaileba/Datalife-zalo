"""Generic sandbox helpers (datamate.helpers, exposed as `dm`): mechanics only, rules as arguments."""
import datetime as dt
import inspect

import pandas as pd
import pytest

from datamate import helpers as dm

T = pd.Timestamp


def test_norm_and_col():
    df = pd.DataFrame(columns=['Mã đơn hàng', 'Tổng tiền (đ)', 'Tổng tiền hàng'])
    assert dm.norm('  Đã HỦY!! ') == 'da huy' and dm.norm('Đã hủy', accents=True) == 'đã hủy'
    assert dm.name(df, 'ma don hang') == 'Mã đơn hàng'
    assert dm.name(df, 'TONG TIEN (D)') == 'Tổng tiền (đ)'
    with pytest.raises(KeyError, match='Closest'):           # a part of a name never picks a column silently
        dm.name(df, 'tong tien')
    with pytest.raises(KeyError, match='Closest'):
        dm.name(df, 'ma khach')


def test_to_num():
    got = dm.to_num(['10,000', '1.234.567 đ', '2,5 kg', '2.5', 7, None, 'abc', '-3']).tolist()
    assert got == [10000, 1234567, 2.5, 2.5, 7, None, None, -3]


def test_to_date():
    got = dm.to_date(['29/01/2025', '2025-01-30', dt.date(2025, 2, 1), 45689, None, 'x'])
    assert got.tolist()[:3] == [T('2025-01-29'), T('2025-01-30'), T('2025-02-01')]
    assert got.isna().tolist()[3:] == [True, True, True]          # numbers are not dates unless asked
    assert dm.to_date([45689], excel_serial=True)[0] == T('2025-02-01')


def test_calendar_windows_take_rules_as_arguments():
    ref = T('2026-03-04')                                         # a Wednesday
    assert dm.week_range(ref, week_start=0) == (T('2026-03-02'), T('2026-03-08'))
    assert dm.week_range(ref, week_start=6) == (T('2026-03-01'), T('2026-03-07'))
    assert dm.week_range(ref, 0, offset=-1) == (T('2026-02-23'), T('2026-03-01'))
    assert dm.month_range(ref) == (T('2026-03-01'), T('2026-03-31'))
    assert dm.month_range(ref, until=ref) == (T('2026-03-01'), ref)
    assert dm.month_range(T('2026-01-15'), offset=-1) == (T('2025-12-01'), T('2025-12-31'))
    assert dm.quarter_range(ref, offset=-1) == (T('2025-10-01'), T('2025-12-31'))
    assert dm.year_range(ref, offset=-1) == (T('2025-01-01'), T('2025-12-31'))
    assert dm.day_range(ref, -1) == (T('2026-03-03'), T('2026-03-03'))
    # No hidden business default: the week start must be chosen.
    assert inspect.signature(dm.week_range).parameters['week_start'].default is inspect.Parameter.empty


def test_between_drop_groups_top_values():
    df = pd.DataFrame({'đơn': ['A', 'A', 'B', 'C', 'D'], 'ngày': ['01/03/2026', '02/03/2026', '31/03/2026', '01/04/2026', '15/03/2026'],
                       'trạng thái': ['xong', 'trả', 'xong', 'xong', 'hủy'], 'tiền': [10, 5, 7, 9, 7]})
    assert list(dm.between(df, 'ngay', *dm.month_range(T('2026-03-10')))['đơn']) == ['A', 'A', 'B', 'D']
    kept = dm.drop_groups(df, 'don', df['trạng thái'].isin(['trả', 'hủy']))
    assert list(kept['đơn']) == ['B', 'C']                        # the whole order A goes, not only its returned line
    ranked = dm.top(df.groupby('đơn')['tiền'].sum(), k=3)
    assert list(ranked.index) == ['A', 'C', 'B'] and list(ranked) == [15, 9, 7]   # B before D on a tie
    assert list(dm.top(df, 'tien', k=2, ascending=True, tie='đơn')['đơn']) == ['A', 'B']
    with pytest.raises(ValueError, match='tie='):             # two text columns: which one is the code?
        dm.top(df, 'tien')
    assert dm.values(df, 'trang thai')['xong'] == 3


def test_dedup_ignores_source_partition():
    df = pd.DataFrame({'đơn': ['A', 'A', 'A', 'B'], 'tiền': [5, 5, 6, 5], '__source': ['T1', 'T2', 'T1', 'T1']})
    assert list(dm.dedup(df)['tiền']) == [5, 6, 5]


def test_tolerant_frame_resolves_unique_normalized_names_only():
    f = dm.TolerantFrame(pd.DataFrame({'Tổng tiền': [1, 2], 'Mã hóa đơn': ['A', 'B'], 'Tiền giảm': [0, 1]}))
    assert list(f['tong tien']) == [1, 2] and list(f[['ma hoa don', 'TỔNG TIỀN']].columns) == ['Mã hóa đơn', 'Tổng tiền']
    assert list(f[f['ma hoa don'] == 'B']['tong tien']) == [2]            # results stay tolerant
    with pytest.raises(KeyError, match='Columns'):
        f['tien']                                                         # substring only: refused, never guessed


def test_object_mask_with_blanks_and_filtered_frame_as_mask():
    t = dm.TolerantFrame(pd.DataFrame({'d': pd.to_datetime(['2026-06-01', '2026-07-01', '2026-06-02']), 'f': [True, None, False]}))
    assert list(t[t['f']].index) == [0]
    picked = dm.between(t, 'd', pd.Timestamp('2026-06-01'), pd.Timestamp('2026-06-30'))
    assert list(t[picked].index) == [0, 2]


def test_days_back_is_a_rolling_window_not_a_calendar_week():
    assert dm.days_back(T('2025-08-23'), 7) == (T('2025-08-17'), T('2025-08-23'))
    assert dm.days_back(T('2025-08-23') - pd.Timedelta(days=1), 1) == (T('2025-08-22'), T('2025-08-22'))


def test_fill_groups_fills_order_cells_on_continuation_lines_only():
    import pandas as pd
    from datamate.layout import fill_groups
    df = pd.DataFrame({'Mã đơn': ['D1', None, None, 'D2', None], 'Trạng thái': ['xong', None, None, 'hủy', None],
                       'Sản phẩm': ['A', 'B', 'C', 'A', 'B'], 'Ghi chú': [None, None, None, 'gấp', None]})
    out, info = fill_groups(df)
    assert info['key'] == 'Mã đơn' and info['rows'] == 3
    assert list(out['Mã đơn']) == ['D1', 'D1', 'D1', 'D2', 'D2'] and list(out['Trạng thái']) == ['xong'] * 3 + ['hủy'] * 2
    assert list(out['Sản phẩm']) == list(df['Sản phẩm']) and list(out['Ghi chú'])[3:] == ['gấp', 'gấp']
    assert out['Ghi chú'][:3].isna().all()


def test_fill_groups_ignores_repeated_keys_and_lone_optional_columns():
    import pandas as pd
    from datamate.layout import fill_groups
    walk_in = pd.DataFrame({'Mã HĐ': ['H1', 'H2', 'H3', 'H4'], 'Mã KH': ['K1', None, 'K1', None], 'Tên KH': ['An', None, 'An', None]})
    assert fill_groups(walk_in)[1] is None                         # customer ids repeat: not one group per id
    barcode = pd.DataFrame({'Mã SP': ['S1', 'S2', 'S3'], 'Barcode': ['893', None, '894'], 'Barcode__raw': ['893', None, '894']})
    assert fill_groups(barcode)[1] is None                         # only the key's own copy is blank with it


def test_factors_read_unit_rules_written_as_text():
    rules = dm.factors(pd.Series(['1 thùng = 6 bịch', '1 lốc = 4 gói; 1 thùng = 24 gói', None, 'không quy đổi'], index=[10, 11, 12, 13]))
    assert rules[['row', 'unit', 'factor', 'base']].values.tolist() == [[10, 'thùng', 6.0, 'bịch'], [11, 'lốc', 4.0, 'gói'],
                                                                      [11, 'thùng', 24.0, 'gói']]
    readme = dm.factors('Quy đổi:\n- Coca Cola 330ml: 1 lốc = 6 lon\n- Bao xi măng: 1 bao 25kg = 25 kg\n- 2 vỉ = 20 viên')
    assert readme[['item', 'unit', 'factor', 'base']].values.tolist() == [['Coca Cola 330ml', 'lốc', 6.0, 'lon'],
                                                                         ['Bao xi măng', 'bao 25kg', 25.0, 'kg'], [None, 'vỉ', 10.0, 'viên']]


def test_name_key_joins_spellings_but_not_other_accents():
    import pandas as pd
    from datamate.helpers import name_key
    k = name_key(pd.Series(['Bạch Duy Giang', 'bạch  duy giang', 'Bach Duy Giang']))
    assert k[0] == k[1] == k[2] == 'bạch duy giang'           # case/spaces, and the unaccented form joins its one accented form
    lines = pd.Series(['Bạch Duy Giang', 'Bách Duy Giang', 'Bạch Duy Giang', 'Bach Duy Giang', 'Le Van A', None])
    k = name_key(lines)
    assert k[0] == k[2] != k[1] and k[3] == 'bach duy giang'  # another accent is another name; two accented forms: no guess
    assert k[4] == 'le van a' and k[5] == ''                # no accented form anywhere: kept as written
    master = pd.Series(['Lê Văn A'])
    assert name_key(lines, master)[4] == name_key(master, lines)[0] == 'lê văn a'   # the master list counts
