from __future__ import annotations

import json
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, "src")
from datamate.shop import HELPERS, Shop, increasing, pct_change

P5 = "experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl"
load = lambda path: {json.loads(line)["id"][2:8]: json.loads(line) for line in open(path, encoding="utf-8") if line.strip()}
PUB_Q, PUB_A = load("public_test/questions.jsonl"), load(P5)
TRAIN_Q, TRAIN_A = load("train/questions.jsonl"), load("train/answers.jsonl")
M = lambda m, y: f"clock.month({m}, {y})"
CASES = {
    "giao hàng": [("ae7e44", "delivery_rounds(clock.this_month())"), ("c78fdf", f"delivery_rounds({M(7,2025)})"), ("c8fde5", f"delivery_rounds({M(11,2025)})"), ("7be693", f"orders_min_rounds({M(6,2025)}, rounds=2)"), ("5c6817", f"orders_min_rounds({M(11,2025)}, rounds=2)"), ("936c6e", f"orders_min_rounds({M(3,2026)}, rounds=2)"), ("59f279", f"delivered_quantity({M(4,2025)}, item='Dây điện Cadivi VCmd 2x2.5 cuộn 100m')"), ("76edb5", f"delivered_quantity({M(3,2026)}, item='Sơn Dulux Weathershield Powerflexx 5L')"), ("cf2c96", f"delivered_quantity({M(5,2025)}, item='Gạch ốp tường Viglacera 30x60 thùng 8 viên')")],
    "nhà thuốc": [("fb4094", "expiring_lots(120)"), ("c3439f", "expiring_value(180)"), ("393267", "expiring_value(start='2026-08-08', end='2026-12-06')"), ("210d0c", "nearest_expiry('Berocca Performance viên sủi tuýp 10 viên')"), ("411cb8", "nearest_expiry('Oresol 245 DHG hộp 20 gói')"), ("481401", "nearest_expiry('Augmentin 625mg hộp 2 vỉ x 7 viên')"), ("0ca19c", "expiring_items(90)"), ("6c4f54", "expiring_items(start='2026-08-08', end='2027-01-05')"), ("4d20e3", "out_of_stock_count()"), ("b01bee", "out_of_stock_count()"), ("c1a3be", "out_of_stock_count('2025-06-01')")],
    "điện thoại": [("8cb214", f"machines_sold({M(5,2026)})"), ("a29355", f"machines_sold({M(6,2025)})"), ("d99e83", f"machines_sold({M(7,2025)})"), ("3fb7bb", f"machines_sold({M(8,2025)})"), ("97a88c", "machines_sold(clock.this_month(), kind='máy cũ')"), ("8a1878", f"machines_sold({M(6,2026)}, line='Samsung Galaxy A56 5G')"), ("e4fc0d", f"machines_sold({M(1,2026)}, line='Xiaomi Redmi Note 14')"), ("d622b7", "machines_sold(clock.this_month(), line='iPhone 16 Pro Max')"), ("12712b", "machines_sold(clock.this_month(), line='Xiaomi Redmi Note 14')"), ("d08785", f"average_machine_price({M(12,2025)})"), ("8e50e2", "average_machine_price(clock.this_month())"), ("473593", "top_machine_lines(clock.quarter(1, 2026), count=3)"), ("7826ef", f"top_machine_lines({M(1,2026)}, count=3)"), ("792e10", f"brand_share({M(10,2025)}, 'Samsung')"), ("3ac94b", f"new_machine_share({M(4,2026)})"), ("4b82c6", "new_machine_share(clock.this_month())"), ("101906", f"trade_in_total({M(2,2026)})"), ("86a32a", f"trade_in_total({M(8,2025)})"), ("0b8546", f"trade_in_total({M(9,2025)})"), ("650a53", f"trade_in_total({M(6,2025)})"), ("701bf3", f"trade_in_total({M(11,2025)})"), ("104054", "trade_in_total(clock.this_month())"), ("3a9665", f"trade_in_order_share({M(4,2026)})"), ("603c21", "trade_in_order_share(clock.this_month())"), ("5bfa54", f"customer_payable({M(6,2025)})"), ("edce3c", f"customer_payable({M(12,2025)})"), ("4c24ac", f"customer_payable({M(2,2026)})"), ("763243", f"customer_payable({M(12,2025)})"), ("8db0ee", "customer_payable(clock.this_month())"), ("78b9ca", "customer_payable(clock.this_month())"), ("94f634", f"average_customer_payable({M(8,2025)})"), ("e0ac21", f"average_customer_payable({M(6,2026)})"), ("f30748", f"average_customer_payable({M(8,2026)})"), ("5a9e0b", "warranty_count(clock.quarter(1, 2026))"), ("a883b3", "warranty_count(clock.quarter(4, 2025))"), ("25af2e", "warranty_rate(clock.quarter(3, 2026))"), ("b2eb16", f"warranted_machines({M(7,2026)})"), ("7c8c12", f"warranted_machines({M(8,2025)})"), ("917d6a", "warranty_top_line(clock.quarter(2, 2026))"), ("059458", "installment_remaining()"), ("51b4d4", "installment_remaining()"), ("435a38", "installment_remaining(customer='Ông Hiếu Anh')"), ("5c0aca", "installment_remaining(customer='Ngô Nam Ngân')"), ("e734e6", "installment_remaining(customer='Lương Khoa Hoàng')"), ("101a2b", "installments_due('Tạ Dũng Long')"), ("8e44f6", "installments_due('Triệu Thu Trang')"), ("16852a", "overdue_customers('2026-03-13')"), ("338d01", "overdue_customers('2026-02-08')"), ("527c4e", "overdue_customers('2026-09-02')"), ("a8d7ce", "installment_overdue('2025-11-26')"), ("b33016", "installment_overdue()"), ("6d42e3", "installment_overdue('2026-06-01')"), ("e2ad9e", "debt_at('2026-09-27')"), ("ff9f21", "debtor_count('2026-06-02')"), ("f37ffc", "[debt_aged('2026-09-23', 0, 7), debt_aged('2026-09-23', 8, 15), debt_aged('2026-09-23', 16)]")],
    "sửa xe": [("33cb3a", f"repair_count({M(8,2025)}, staff='Hà Loan Đạt')"), ("827118", f"repair_count({M(5,2026)}, staff='Đoàn Bảo Phúc')"), ("f3a93a", f"repair_amount({M(7,2026)}, staff='Ha Loan Dat')"), ("027f54", f"commission({M(8,2025)}, staff='Đoàn Bảo Phúc')"), ("1c0046", f"commission_table({M(7,2026)})"), ("20b7bb", f"commission_table({M(3,2026)})"), ("c69505", f"commission_table({M(11,2025)})"), ("a225dc", f"busiest_staff({M(9,2025)})"), ("32733a", f"top_repair_model({M(10,2025)})"), ("5ec780", f"repair_vehicles({M(1,2026)}, model='Air Blade')"), ("b6d750", f"repair_vehicles({M(12,2025)}, model='Wave Alpha')"), ("07e250", "repair_vehicles(clock.this_month(), model='SH Mode')"), ("7f91e4", f"repeat_vehicles({M(10,2025)}, min_visits=2)"), ("c3158f", "repeat_vehicles(clock.between('2025-09-01', '2025-11-30'), min_visits=2)"), ("4e280a", f"repair_count({M(8,2025)}, job='điện')"), ("7de8d5", f"repair_count({M(9,2025)}, job='láp')"), ("c38425", "repair_count(clock.this_month(), job='vá')"), ("c80365", "warranty_repairs(clock.quarter(2, 2026))"), ("eb6064", f"warranty_repairs({M(8,2026)})"), ("6b5bd6", "warranty_share(clock.quarter(4, 2025))"), ("569dcd", f"weekday_average({M(3,2026)}, 'thứ tư')"), ("8ce765", "weekday_average(clock.this_month(), 'thứ ba')"), ("05cde7", f"average_ticket({M(2,2026)})"), ("34a5b4", f"average_ticket({M(8,2025)})"), ("ec8d9c", f"average_ticket({M(1,2026)})")],
    "mẹ và bé": [("5cd8a3", f"order_fee_total({M(12,2025)}, 'voucher')"), ("1c7bef", f"order_fee_total({M(6,2026)}, 'voucher')"), ("77c325", "order_fee_total(clock.this_month(), 'voucher')"), ("4497ce", f"order_fee_total({M(5,2026)}, 'ship')"), ("5355ac", f"order_fee_total({M(6,2026)}, 'ship')"), ("dae195", "order_fee_total(clock.this_month(), 'ship')"), ("dbb9f4", f"order_fee_total({M(6,2026)}, 'points')"), ("b362a4", f"quantity({M(5,2026)}, group='bỉm tã', size='M')"), ("78f694", "quantity(clock.this_month(), group='bỉm tã', size='L')"), ("ed68b2", "group_share(clock.this_month(), 'bỉm tã', size='M')"), ("94a2e7", "group_share(clock.this_month(), 'bỉm tã', size='XL')"), ("95f39e", f"group_share({M(1,2026)}, 'bỉm tã', size='NB')"), ("7d236c", "group_share(clock.this_month(), 'bỉm tã', brand='Bobby')"), ("ab0d15", "group_share(clock.this_month(), 'bỉm tã', brand='Moony')"), ("dcd34f", f"group_share({M(2,2026)}, 'bỉm tã', brand='Huggies')"), ("1fc800", "quantity(clock.this_month(), group='sữa bột', size='Số 4')"), ("24a84f", "quantity(clock.this_month(), group='sữa bột', size='Số 2')"), ("14a10f", f"top_brand({M(3,2026)}, group='sữa bột', size='Số 2')"), ("e36c0b", f"new_members({M(5,2026)})")],
    "từ rulebook, đổi giá": [("9d8949", "ranking(by='customer', metric='average_order', min_orders=3, period=clock.month(5, 2026)).index[0]"), ("b38db1", "ranking(by='customer', metric='cancelled', period=clock.quarter(3, 2025)).index[0]"), ("a7dd46", "ranking(by='item', metric='orders', period=clock.month(7, 2025)).index[0]"), ("3f61cd", "ranking(by='day', metric='orders', period=clock.month(8, 2025)).index[0]"), ("735ea0", "ranking(by='customer', metric='days', period=clock.month(3, 2025)).index[0]"), ("203767", "ranking(by='hour', metric='orders', period=clock.month(3, 2026)).index[0]"), ("08b923", "main_supplier(clock.month(12, 2025))"), ("d54752", "ranking(by='staff', period=clock.month(1, 2026)).index[0]"), ("501cc0", "price_effect('Acyclovir Stella kem 5% tuýp 5g', price=18000, days=30)"), ("5e7b3b", "price_effect('Hapacol 250 hộp 24 gói', price=2100, days=7)"), ("8c88fc", "price_effect('Phosphalugel hộp 26 gói', price=5400, days=30)"), ("45d6cb", "price_effect('Trà vải (L)', price=47000, days=30)"), ("c810dc", "price_effect('Topping Thạch cà phê', price=7400, days=30)"), ("dd2362", "price_effect('Bạc xỉu (M)', price=35000, days=14)")],
}
GOLD = {
    "giao hàng": [(i, "delivery_rounds(PERIOD)") for i in ("0174cb", "047586", "087a40", "440545", "4632f7", "5d5a5f", "82b3c2")],
}
ENTITY = {"khach_hang": 0}
cache = {}


def env_for(dataset: str, question: dict) -> dict:
    key = (question["business_id"], question["as_of_date"])
    if key not in cache:
        cache[key] = Shop(f"artifacts/norm/{dataset}/{question['business_id']}", as_of=question["as_of_date"], calendar=f"{dataset}/calendar.csv")
    shop = cache[key]
    return {"clock": shop.clock, "pct_change": pct_change, "increasing": increasing, **{name: getattr(shop, name) for name in HELPERS}}


def same(got, want):
    if isinstance(want, dict):
        return isinstance(got, dict) and sorted(map(tuple, got["rows"]), key=str) == sorted(map(tuple, want["rows"]), key=str)
    if hasattr(got, "item"):
        got = got.item()
    return got == want or (isinstance(got, (int, float)) and isinstance(want, (int, float)) and abs(got - want) < 1e-6) or (isinstance(got, str) and isinstance(want, str) and got.casefold() == want.casefold())


total = passed = 0
for group, cases in CASES.items():
    hits = 0
    for short, code in cases:
        q = PUB_Q[short]
        try:
            got = eval(code, env_for("public_test", q))
        except Exception as error:
            got = f"EXC {type(error).__name__}: {str(error)[:90]}"
        ok = same(got, PUB_A[short]["answer"])
        hits += ok
        if not ok:
            print("  NO", group, short, code[:60], "|", str(got)[:60], "| ref", str(PUB_A[short]["answer"])[:60])
    total += len(cases)
    passed += hits
    print(f"{group:24s} {hits}/{len(cases)}")
print("public", passed, "/", total)
