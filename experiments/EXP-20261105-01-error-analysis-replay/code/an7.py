import glob,os,re,sys,warnings,collections
warnings.filterwarnings('ignore')
import pandas as pd
sys.path.insert(0,'src')
from datamate.shop import Shop
print('=== dropped audit')
for ds in ('public_test','train'):
    tot=collections.Counter();ton=collections.Counter()
    for p in glob.glob(f'artifacts/norm/{ds}/*/*.dropped.csv'):
        d=pd.read_csv(p,dtype=str).fillna('')
        if 'drop_reason' not in d: continue
        shop=p.split('/')[-2];base=os.path.basename(p)
        for reason,g in d.groupby('drop_reason'):
            tot[(reason)]+=len(g)
            if reason=='subtotal':
                txt=g.astype(str).agg(' '.join,axis=1)
                n=txt.str.contains(r'\bTống ').sum()
                if n: ton[(shop,base[:40])]+=n
    print(ds,'reasons',tot.most_common(8));print(' Tống rows',sum(ton.values()),'in',len(ton),'files');
    for k,v in ton.most_common(16): print('   ',k,v)
print('=== verify dev_010')
s=Shop('artifacts/norm/public_test/dev_010',as_of='2026-09-06',calendar='public_test/calendar.csv')
dc=pd.read_csv('artifacts/norm/public_test/dev_010/customers_khach_hang.dropped.csv',dtype=str)
print(dc[['Khách lẻ/sỉ','Loại khách','Mã khách','drop_reason']].to_string())
l=s.lines
codes=dc[dc['Loại khách']=='thân thiết']['Mã khách'].tolist()
per=l[(l.order_date>='2026-04-01')&(l.order_date<'2026-05-01')&l.is_revenue]
print('T4/2026 revenue of dropped thân thiết',per[per.customer_code.isin(codes)].line_amount.sum() if 'line_amount' in per else per.columns.tolist(),'gap',138500500-134079500)
print('=== verify dev_003 Kiểu khách')
c=pd.read_csv('artifacts/norm/public_test/dev_003/customers_banhang_tonghop_2025_banhang_khachhang.csv',dtype=str)
s=Shop('artifacts/norm/public_test/dev_003',as_of='2026-08-21',calendar='public_test/calendar.csv')
codes=c[c['Kiểu khách']=='thân thiết'].customer_code.tolist()
dd=pd.read_csv('artifacts/norm/public_test/dev_003/customers_banhang_tonghop_2025_banhang_khachhang.dropped.csv',dtype=str)
codes2=codes+dd[dd['Kiểu khách']=='thân thiết']['Mã KH mua'].tolist()
per=s.orders
print(per.columns.tolist()[:30])
for lab,cc in (('kept',codes),('+dropped',codes2)):
    tot=sum(s.revenue(s.clock.month(8,2025),customer=x) if False else 0 for x in [])
    l=s.lines;m=l[(l.order_date>='2025-08-01')&(l.order_date<'2025-09-01')&l.is_revenue&l.customer_code.isin(cc)]
    print(lab,'T8/2025 line_amount',m.line_amount.sum() if 'line_amount' in m else None,'ref 39571500')
print('=== raw vs norm')
for s_ in ('dev_008','dev_014','dev_007','dev_011'):
    print(s_,'raw',[os.path.relpath(p,f'public_test/data/{s_}') for p in glob.glob(f'public_test/data/{s_}/**/*',recursive=True) if os.path.isfile(p)])
    print('  norm',[os.path.basename(p) for p in glob.glob(f'artifacts/norm/public_test/{s_}/*.csv') if 'dropped' not in p])
    print('  prep dropped',[os.path.basename(p) for p in glob.glob(f'artifacts/norm/public_test/{s_}/*dropped*')])
