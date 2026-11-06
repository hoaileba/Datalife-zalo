from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, "src")
from datamate_agent.question_norm import normalize

M = "clock.month(5, 2026)"
ROWS = [
    ("delivery_rounds", "delivery", "number", "delivery_rounds(clock.month(9, 2025))", ("Tháng 9/2025 tiệm giao bao nhiêu đợt hàng?", "co may dot giao hang trong thang 9/2025", "thang nay xe cho duoc may dot hang")),
    ("orders_min_rounds", "delivery", "number", "orders_min_rounds(clock.month(9, 2025), rounds=2)", ("Các đơn đặt tháng 9/2025 có mấy đơn đã được giao từ 2 đợt trở lên?", "don dat th9/2025 toi hnay co bnhiu don cho thanh 2 dot tro len")),
    ("delivered_quantity", "delivery", "number", "delivered_quantity(clock.month(9, 2025), item='Xi măng')", ("Các đơn đặt tháng 9/2025, tới hôm nay đã chở đi bao nhiêu bao Xi măng?",)),
    ("expiring_lots", "pharmacy", "number", "expiring_lots(60)", ("Hiện còn bao nhiêu lô chưa bán hết có hạn dùng trong 60 ngày tới?", "con may lo ton het han trong 60 ngay toi")),
    ("expiring_value", "pharmacy", "number", "expiring_value(60)", ("Hàng sẽ hết hạn trong 60 ngày tới còn tồn bao nhiêu tiền vốn?", "may lo con ton hsd trong khoang do dang dong bnhiu tien von")),
    ("expiring_items", "pharmacy", "list", "expiring_items(60)", ("Liệt kê các sản phẩm còn lô tồn hết hạn trong 60 ngày tới.", "nhung sp nao con hang co hsd trong 60 ngay toi")),
    ("nearest_expiry", "pharmacy", "date", "nearest_expiry('Tên thuốc')", ("Lô Tên thuốc gần hết hạn nhất có hạn dùng ngày nào?", "lo Tên thuốc can date nhat het han ngay nao")),
    ("out_of_stock", "pharmacy", "number", "out_of_stock_count('2026-02-01')", ("Cuối ngày 01/02/2026 tiệm có mấy mặt hàng hết hàng?", "het ngay hom nay dang dut hang may mat hang", "cuoi ngay co may mat hang chay hang")),
    ("machines_sold", "phone", "number", f"machines_sold({M})", ("Tháng 5/2026 bán được bao nhiêu máy, không tính phụ kiện?", "th5/2026 ban ra tat ca bao nhieu chiec dien thoai, ca may moi lan may cu", "thang 5/2026 tiem ban duoc may chiec dien thoai")),
    ("machines_line", "phone", "number", f"machines_sold({M}, line='Dòng máy')", ("Tháng 5/2026 bán được mấy chiếc Dòng máy?", "05/2026 ban dc bnhiu may Dòng máy")),
    ("machines_kind", "phone", "number", "machines_sold(clock.this_month(), kind='máy cũ')", ("Tháng này bán được bao nhiêu điện thoại cũ?",)),
    ("top_lines", "phone", "list", f"top_machine_lines({M}, count=3)", ("Top 3 dòng máy bán nhiều máy nhất tháng 5/2026?", "3 dong may nao ban duoc nhieu may nhat")),
    ("brand_share", "phone", "percent", f"brand_share({M}, 'Hãng')", ("Tháng 5/2026 máy Hãng chiếm bao nhiêu phần trăm tổng số máy bán ra?",)),
    ("new_share", "phone", "percent", f"new_machine_share({M})", ("Tháng 5/2026 máy mới chiếm mấy phần trăm tiền bán máy, bỏ phụ kiện?",)),
    ("average_price", "phone", "number", f"average_machine_price({M})", ("Tháng 5/2026 không tính phụ kiện, trung bình một máy bán được bao nhiêu tiền?",)),
    ("trade_in", "phone", "number", f"trade_in_total({M})", ("Tháng 5/2026 tổng tiền thu máy cũ của khách là bao nhiêu?", "tien thu may cu tru vao don cong lai bnhiu")),
    ("trade_in_share", "phone", "percent", f"trade_in_order_share({M})", ("Tháng 5/2026 bao nhiêu phần trăm đơn có thu máy cũ của khách?",)),
    ("payable", "phone", "number", f"customer_payable({M})", ("Tháng 5/2026 khách phải trả tổng cộng bao nhiêu, sau khi trừ bớt và tiền máy cũ?", "tong tien khach phai tra thang 5/2026")),
    ("payable_avg", "phone", "number", f"average_customer_payable({M})", ("Tháng 5/2026 mỗi đơn khách phải trả trung bình bao nhiêu, đã trừ bớt và máy cũ?",)),
    ("installment_left", "installment", "number", "installment_remaining()", ("Đến hết hôm nay các hợp đồng trả góp còn lại bao nhiêu tiền chưa góp, tính cả kỳ chưa tới hạn?",)),
    ("installment_customer", "installment", "number", "installment_remaining(customer='Tên khách')", ("Đến hết hôm nay khách Tên khách còn thiếu bao nhiêu tiền góp, kể cả kỳ chưa tới hạn?",)),
    ("installment_overdue", "installment", "number", "installment_overdue('2026-02-01')", ("Đến hết ngày 01/02/2026 khách còn chưa đóng bao nhiêu tiền thuộc các kỳ góp đã quá hạn?", "tien cham gop cua khach tra gop tong cong bnhiu")),
    ("overdue_customers", "installment", "number", "overdue_customers('2026-02-01')", ("Đến ngày 01/02/2026 có mấy khách trả góp còn kỳ quá hạn?", "bnhiu khach qua han gop")),
    ("installments_due", "installment", "number", "installments_due('Tên khách')", ("Hết hôm nay khách Tên khách đã tới hạn mấy kỳ góp, tính cả kỳ hạn hôm nay?",)),
    ("warranty_count", "warranty", "number", "warranty_count(clock.quarter(1, 2026))", ("Quý 1/2026 tiệm nhận bảo hành bao nhiêu lượt máy?", "co may luot khach dem may toi bao hanh")),
    ("warranty_rate", "warranty", "percent", "warranty_rate(clock.quarter(1, 2026))", ("Quý 1/2026 lượt bảo hành so với số máy bán chiếm bao nhiêu phần trăm?",)),
    ("warranted", "warranty", "number", f"warranted_machines({M})", ("Máy bán tháng 5/2026 tới nay có bao nhiêu máy đã mang tới bảo hành?",)),
    ("warranty_line", "warranty", "string", "warranty_top_line(clock.quarter(1, 2026))", ("Quý 1/2026 dòng máy nào có nhiều lượt bảo hành nhất?",)),
    ("repair_count", "repair", "number", f"repair_count({M}, staff='Tên thợ')", ("Tháng 5/2026 thợ Tên thợ sửa được bao nhiêu lượt xe?",)),
    ("repair_job", "repair", "number", f"repair_count({M}, job='vá')", ("Tháng 5/2026 bao nhiêu phiếu sửa có vá ruột xe?", "luot xe sua dien thang 5/2026 bnhiu")),
    ("repair_amount", "repair", "number", f"repair_amount({M}, staff='Tên thợ')", ("Tháng 5/2026 tiền hàng các phiếu thợ Tên thợ làm cộng lại bao nhiêu?",)),
    ("repair_vehicles", "repair", "number", f"repair_vehicles({M}, model='Dòng xe')", ("Tháng 5/2026 có bao nhiêu chiếc xe Dòng xe khác nhau vào tiệm?", "bn chiec Dòng xe khac nhau zo sua")),
    ("top_model", "repair", "string", f"top_repair_model({M})", ("Tháng 5/2026 dòng xe nào đem lại nhiều tiền sửa nhất?",)),
    ("commission", "repair", "number", f"commission({M}, staff='Tên thợ')", ("Tháng 5/2026 thợ Tên thợ được bao nhiêu tiền hoa hồng?",)),
    ("commission_table", "repair", "table", f"commission_table({M})", ("Bảng hoa hồng từng thợ tháng 5/2026, xếp tiền giảm dần.", "cho xin bang tien hoa hong moi tho")),
    ("warranty_repairs", "repair", "number", f"warranty_repairs({M})", ("Tháng 5/2026 tiệm nhận bao nhiêu phiếu bảo hành?", "bnhiu luot xe quay lai bao hanh")),
    ("warranty_share_repair", "repair", "percent", "warranty_share(clock.quarter(1, 2026))", ("Quý 1/2026 phiếu bảo hành chiếm bao nhiêu phần trăm số phiếu thu tiền?",)),
    ("average_ticket", "repair", "number", f"average_ticket({M})", ("Tháng 5/2026 trung bình một phiếu thu tiền được bao nhiêu?", "binh quan 1 phieu sua het bnhiu tien")),
    ("weekday_average", "repair", "number", f"weekday_average({M}, 'thứ tư')", ("Tháng 5/2026 trung bình mỗi thứ Tư tiệm sửa mấy lượt xe?",)),
    ("busiest", "repair", "string", f"busiest_staff({M})", ("Tháng 5/2026 ai là thợ chăm chỉ nhất?",)),
    ("repeat", "repair", "number", f"repeat_vehicles({M}, min_visits=2)", ("Tháng 5/2026 có mấy chiếc xe vô sửa từ 2 lần trở lên?", "bnhiu xe khach quen tuc xe sua tu 2 lan tro len")),
    ("fee_voucher", "baby", "number", f"order_fee_total({M}, 'voucher')", ("Tháng 5/2026 voucher giảm cho khách tổng bao nhiêu?",)),
    ("fee_ship", "baby", "number", f"order_fee_total({M}, 'ship')", ("Tháng 5/2026 tổng tiền phí ship là bao nhiêu?",)),
    ("fee_points", "baby", "number", f"order_fee_total({M}, 'points')", ("Tháng 5/2026 khách dùng điểm trừ được bao nhiêu tiền?",)),
    ("size_quantity_baby", "baby", "number", f"quantity({M}, group='bỉm tã', size='M')", ("Tháng 5/2026 bỉm size M của mọi hãng bán được mấy bịch?",)),
    ("milk_number", "baby", "number", f"quantity({M}, group='sữa bột', size='Số 2')", ("Tháng 5/2026 bán được mấy lon sữa bột số 2, gộp mọi hãng?",)),
    ("size_share", "baby", "percent", f"group_share({M}, 'bỉm tã', size='M')", ("Tháng 5/2026 bỉm size M chiếm bao nhiêu phần trăm tổng số bịch bỉm?",)),
    ("brand_share_baby", "baby", "percent", f"group_share({M}, 'bỉm tã', brand='Hãng')", ("Tháng 5/2026 bỉm Hãng chiếm bao nhiêu phần trăm số bịch bỉm, gộp mọi size?",)),
    ("top_brand", "baby", "string", f"top_brand({M}, group='sữa bột', size='Số 2')", ("Tháng 5/2026 sữa bột số 2 của hãng nào bán nhiều lon nhất?",)),
    ("new_members", "baby", "number", f"new_members({M})", ("Số khách thành viên đăng ký mới tháng 5/2026?",)),
    ("gross_profit_total", None, "number", f"gross_profit({M})", ("Lãi gộp tháng 5/2026 được bao nhiêu?", "lai gop 5/2026 bnhiu", "loi nhuan gop thang 5/2026")),
    ("net_profit_total", None, "number", f"net_profit({M})", ("Lãi ròng tháng 5/2026 là bao nhiêu?", "thang 5/2026 tru het chi phi quan con lai bnhiu")),
    ("debtor_count_total", None, "number", "debtor_count('2026-02-01')", ("Đến hết ngày 01/02/2026 số khách còn công nợ là bao nhiêu?", "tinh den het ngay 01/02/2026 co bao nhieu khach con no")),
    ("stock_value_total", None, "number", "stock_value()", ("Hết hôm nay hàng tồn trong kho tính theo giá vốn là bao nhiêu tiền?", "hang con du trong kho tinh gia von dang bao nhieu tien")),
    ("due_after", None, "number", "due_orders(after=clock.as_of)", ("Tới hôm nay có mấy đơn bán chịu ghi ngày phải trả muộn hơn hôm nay?",)),
    ("due_in", None, "number", f"due_orders({M})", ("Tính tới hôm nay có mấy đơn bán chịu có ngày phải trả trong tháng 5/2026?",)),
    ("unit_total", None, "number", "quantity(clock.last_week(), unit='ly')", ("Tuần trước quán bán được tổng cộng mấy ly?", "tuan truoc ban duoc bao nhieu goi", "hom qua ban ra duoc may lon", "bnhiu dia")),
    ("unit_group", None, "number", f"quantity({M}, group='Nhóm')", ("Tháng 5/2026 nhóm Nhóm bán được bao nhiêu ly?",)),
    ("big_spender", None, "string", f"ranking(by='customer', metric='average_order', min_orders=3, period={M}).index[0]", ("Khách sộp nhất tháng 5/2026 là ai?",)),
    ("flaky_customer", None, "string", f"ranking(by='customer', metric='cancelled', period={M}).index[0]", ("Tháng 5/2026 ai là khách hay đổi ý nhất?",)),
    ("loyal_customer", None, "string", f"ranking(by='customer', metric='days', period={M}).index[0]", ("Tháng 5/2026 khách nào trung thành nhất?",)),
    ("favorite_item", None, "string", f"ranking(by='item', metric='orders', period={M}).index[0]", ("Tháng 5/2026 hàng nào được khách ưa chuộng nhất?",)),
    ("busy_day", None, "date", f"ranking(by='day', metric='orders', period={M}).index[0]", ("Tháng 5/2026 ngày nào đắt khách nhất?",)),
    ("peak_hour", None, "number", f"ranking(by='hour', metric='orders', period={M}).index[0]", ("Tháng 5/2026 giờ cao điểm trong ngày là mấy giờ?",)),
    ("main_supplier_q", None, "string", f"main_supplier({M})", ("Tháng 5/2026 nhà cung cấp chính của cửa hàng là ai?",)),
    ("price_by_level", None, "percent", "price_effect('Tên hàng', price=47000, days=30)", ("Từ khi Tên hàng lên giá 47.000đ, 30 ngày đầu bán nhiều hay ít hơn 30 ngày liền trước bao nhiêu phần trăm?", "sau lan tang gia Tên hàng len 47.000 dong so luong ban 30 ngay thay doi bao nhieu %")),
    ("purchase_qty", None, "number", f"purchase_quantity({M}, item='Tên hàng')", ("Tháng 5/2026 nhập về bao nhiêu viên Tên hàng?",)),
    ("multi_months", None, "list", "[revenue(clock.month(3, 2026)), revenue(clock.month(4, 2026)), revenue(clock.month(5, 2026))]", ("Doanh thu tháng 3, 4, 5 năm 2026 lần lượt là bao nhiêu?", "dthu th3, th4, th5 moi thang duoc nhieu")),
    ("multi_payment", None, "list", "[revenue(clock.month(5, 2026), payment='tiền mặt'), revenue(clock.month(5, 2026), payment='ví điện tử')]", ("Tháng 5/2026 doanh thu đơn trả tiền mặt và đơn trả ví điện tử lần lượt bao nhiêu?",)),
    ("multi_channel", None, "list", "[revenue(clock.month(5, 2026), channel='tại quầy'), revenue(clock.month(5, 2026), channel='điện thoại')]", ("Tháng 5/2026 doanh thu đơn tại quầy và đơn qua điện thoại mỗi bên bao nhiêu?",)),
    ("average_wording", None, "number", f"average_order({M})", ("Doanh thu bình quân một đơn tháng 5/2026 là bao nhiêu?", "dthu binh quan 1 dh th5/2026", "bin quan moi don bao nhieu tien")),
    ("group_top_item", None, "string", f"ranking(by='item', metric='revenue', period={M}, group='Nhóm').index[0]", ("Tháng 5/2026 trong nhóm Nhóm mặt hàng nào có doanh thu cao nhất?",)),
    ("group_order_count", None, "number", f"order_count({M}, group='Nhóm')", ("Tháng 5/2026 bao nhiêu đơn có ít nhất một mặt hàng nhóm Nhóm?",)),
]
PLACEHOLDERS = {"Tên hàng": "<item>", "Tên thuốc": "<item>", "Xi măng": "<item>", "Nhóm": "<group>", "Tên khách": "<customer>"}


def masked(question: str) -> str:
    text = question
    for name, mark in PLACEHOLDERS.items():
        text = text.replace(name, mark)
    return re.sub(r"\d+", "#", normalize(text))


rows = [{"question": q, "masked": masked(q), "answer_type": kind, "code": code, "intent": f"cur_{intent}", "requires": requires} for intent, requires, kind, code, questions in ROWS for q in questions]
open("src/datamate_agent/prompts/library_curated.jsonl", "w", encoding="utf-8").write("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
print(len(rows), "examples", len(ROWS), "intents", rows[0]["masked"], "|", rows[6]["masked"])
