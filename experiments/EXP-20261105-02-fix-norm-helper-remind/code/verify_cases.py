import json,sys,warnings;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
from datamate.shop import Shop,_note_left
Q={json.loads(l)['id'][2:8]:json.loads(l) for l in open('public_test/questions.jsonl')}
ROOT=sys.argv[1] if len(sys.argv)>1 else 'artifacts/norm/public_test'
def run(i,f,ref):
    q=Q[i]
    try:
        s=Shop(f"{ROOT}/{q['business_id']}",as_of=q['as_of_date'],calendar='public_test/calendar.csv')
        got=f(s); got=got.item() if hasattr(got,'item') else got
    except Exception as e: got='EXC '+str(e)[:110]
    print(i,q['business_id'][-3:],'OK ' if got==ref else 'NO ',got,'ref',ref)
T=[('ce8675',lambda s:s.purchase_minus_sold(s.clock.month(10,2025),item='Bánh tiramisu'),-34),('b4171c',lambda s:s.purchase_minus_sold(s.clock.month(3,2026),item='Bánh croissant'),23),
('c788eb',lambda s:s.purchase_minus_sold(s.clock.month(9,2025),item='Hagifen 400mg DHG hộp 10 vỉ x 10 viên'),26),('d770b2',lambda s:s.purchase_minus_sold(s.clock.month(11,2025),item='Biosubtyl-II hộp 25 gói'),41),
('600224',lambda s:s.purchase_minus_sold(s.clock.month(9,2025),item='Vitamin C 500mg Quapharco hộp 10 vỉ x 10 viên'),20),('fbaf20',lambda s:s.purchase_quantity(s.clock.month(6,2025),item='Tiffy Dey hộp 25 vỉ x 4 viên'),1500),
('624351',lambda s:s.revenue(s.clock.month(6,2025),payment='chuyển khoản'),80104100),('605c59',lambda s:[s.revenue(s.clock.this_month(),payment='tiền mặt'),s.revenue(s.clock.this_month(),payment='ví điện tử')],[62390000,7123000]),
('6bf3c6',lambda s:round(100*s.revenue(s.clock.month(1,2026),channel='tại quầy')/s.revenue(s.clock.month(1,2026)),2),89.94),('219f01',lambda s:[s.revenue(s.clock.month(1,2026),channel='tại quầy'),s.revenue(s.clock.month(1,2026),channel='điện thoại')],[648052000,31254500]),
('6172ed',lambda s:[s.revenue(s.clock.month(3,2026),channel='Zalo OA'),s.revenue(s.clock.month(3,2026),channel='điện thoại')],[41119000,41361000]),('f9912e',lambda s:s.revenue(s.clock.month(6,2026),staff='Võ Trung Hoa'),90158700),('3b7061',lambda s:s.revenue(s.clock.month(4,2025),staff='Từ Hùng Hằng'),77101300),
('b2bbe9',lambda s:s.quantity(s.clock.month(2,2025),item='Cà phê sữa (M)'),272),('dec759',lambda s:s.quantity(s.clock.month(4,2026),item='Latte (M)'),121),('c64c6d',lambda s:s.quantity(s.clock.this_month(),size='M'),2583),('cfcb5f',lambda s:s.quantity(s.clock.this_month(),size='L'),1350),
('54bbf0',lambda s:s.ranking(by='item',metric='quantity',period=s.clock.month(6,2025)).index[:3].tolist(),['Cà phê sữa (M)','Trà đào cam sả (M)','Cà phê đen (M)']),
('fbf739',lambda s:s.debt_at('2026-07-22'),4549169),('db00ae',lambda s:s.debtor_count('2026-07-22'),15),('f9a0fa',lambda s:s.debt_aged('2026-07-22',11),2771668),('8a85aa',lambda s:[s.debt_aged('2026-07-22',0,7),s.debt_aged('2026-07-22',8,15),s.debt_aged('2026-07-22',16)],[1429334,1961667,1158168]),
('81bd98',lambda s:s.revenue(s.clock.month(4,2026),customer_group='thân thiết'),138500500),('ba2fc1',lambda s:s.revenue(s.clock.month(8,2025),customer_group='thân thiết'),39571500),('f98cec',lambda s:round(100*s.revenue(s.clock.month(1,2026),customer_group='thân thiết')/s.revenue(s.clock.month(1,2026)),2),17.23),('12d780',lambda s:s.average_order(s.clock.month(12,2025),customer_group='thân thiết'),73226),
('84ccc0',lambda s:round(100*s.revenue(s.clock.month(8,2026),customer_group='thân thiết')/s.revenue(s.clock.month(8,2026)),2),21.15),('262121',lambda s:s.average_order(s.clock.this_month(),customer_group='thân thiết'),561385),
('ee2df6',lambda s:s.debtors('2026-05-08').index[0],'Tống Thu Hương'),('c28a03',lambda s:s.quantity(s.clock.last_n_days(7),unit='ly'),1285),('ce1627',lambda s:s.quantity(s.clock.last_n_days(30),unit='ly'),5868)]
for i,f,ref in T: run(i,f,ref)
