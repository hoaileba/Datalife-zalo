import json,re,sys,warnings;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
import pandas as pd
from datamate.shop import Shop
Q={json.loads(l)['id'][2:8]:json.loads(l) for l in open('public_test/questions.jsonl')}
def run(i,f,ref):
    q=Q[i]
    try:
        s=Shop(f"artifacts/norm/public_test/{q['business_id']}",as_of=q['as_of_date'],calendar='public_test/calendar.csv')
        got=f(s)
        got=got.item() if hasattr(got,'item') else got
    except Exception as e: got='EXC '+str(e)[:90]
    print(i,q['business_id'][-3:],'OK ' if got==ref else 'NO ',got,'ref',ref)
T=[('c28a03',lambda s:s.quantity(s.clock.last_n_days(7)),1285),('ce1627',lambda s:s.quantity(s.clock.last_n_days(30)),5868),
('54e2a0',lambda s:s.quantity(s.clock.month(1,2026),group='cà phê'),2507),('929a9d',lambda s:s.quantity(s.clock.month(9,2025),group='trà sữa'),1101),
('393d0d',lambda s:s.quantity(s.clock.yesterday(),unit='lon'),81),('a6a66b',lambda s:s.quantity(s.clock.yesterday(),unit='lon'),79),
('1a35be',lambda s:s.quantity(s.clock.this_week(),unit='đĩa'),1581),('15a889',lambda s:s.quantity(s.clock.last_week(),unit='đĩa'),1708),
('954278',lambda s:s.quantity(s.clock.last_n_days(30),unit='gói'),5322),('c6bfd1',lambda s:s.quantity(s.clock.last_week(),unit='gói'),1282),
('ce8675',lambda s:s.purchase_minus_sold(s.clock.month(10,2025),item='Bánh tiramisu'),-34),('b4171c',lambda s:s.purchase_minus_sold(s.clock.month(3,2026),item='Bánh croissant'),23),
('c788eb',lambda s:s.purchase_minus_sold(s.clock.month(9,2025),item='Hagifen 400mg DHG hộp 10 vỉ x 10 viên'),26),('d770b2',lambda s:s.purchase_minus_sold(s.clock.month(11,2025),item='Biosubtyl-II hộp 25 gói'),41),
('624351',lambda s:s.revenue(s.clock.month(6,2025),payment='chuyển khoản'),80104100),('605c59',lambda s:[s.revenue(s.clock.this_month(),payment='tiền mặt'),s.revenue(s.clock.this_month(),payment='ví điện tử')],[62390000,7123000]),
('6bf3c6',lambda s:round(100*s.revenue(s.clock.month(1,2026),channel='store')/s.revenue(s.clock.month(1,2026)),2),89.94),
('791de9',lambda s:s.ranking(by='staff',period=s.clock.month(7,2026)).index[0],'NV005'),('3f61cd',lambda s:s.ranking(by='day',metric='orders',period=s.clock.month(8,2025)).index[0],'2025-08-02'),
('b12710',lambda s:s.revenue(s.clock.month(4,2026),staff='Lương Chi Đức'),20339500),('f9912e',lambda s:s.revenue(s.clock.month(6,2026),staff='Võ Trung Hoa'),90158700),
('fbaf20',lambda s:s.purchase_minus_sold(s.clock.month(6,2025),item='Tiffy Dey hộp 25 vỉ x 4 viên')+s.quantity(s.clock.month(6,2025),item='Tiffy Dey hộp 25 vỉ x 4 viên'),1500),
('7b4571',lambda s:s.purchase_cost(s.clock.month(6,2025)),182107800),('3766bf',lambda s:s.order_count(s.clock.quarter(1,2026)),842),('570280',lambda s:s.gross_profit(s.clock.month(2,2026)),64003275)]
for i,f,ref in T: run(i,f,ref)
d=pd.read_csv('artifacts/norm/public_test/dev_008/sales.csv',dtype=str)
o=d[d.note.notna()].drop_duplicates('order_id')
open_=o[~o.note.str.contains(r'đủ|hết|xong',case=False)]
print('dev_008 orders with open note',len(open_),'customers',open_.customer_code.nunique(),'ref debtor_count 15',open_.note.head(4).tolist())
