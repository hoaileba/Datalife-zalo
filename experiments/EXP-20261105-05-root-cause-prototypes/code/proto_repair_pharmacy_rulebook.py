import json,re,sys,warnings,datetime as dt;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
import pandas as pd
from datamate.shop import Shop,_folded,pct_change
from datamate.norm import parse_money,parse_datetime
Q={json.loads(l)['id'][2:8]:json.loads(l) for l in open('public_test/questions.jsonl')}
C={}
def shop(i):
    q=Q[i];k=(q['business_id'],q['as_of_date'])
    if k not in C:C[k]=Shop(f"artifacts/norm/public_test/{q['business_id']}",as_of=q['as_of_date'],calendar='public_test/calendar.csv')
    return C[k]
res={}
def T(group,i,f,ref):
    s=shop(i)
    try:
        got=f(s);got=got.item() if hasattr(got,'item') else got
    except Exception as e: got='EXC '+type(e).__name__+' '+str(e)[:70]
    ok=got==ref or (isinstance(got,float) and isinstance(ref,(int,float)) and abs(got-ref)<1e-6)
    res.setdefault(group,[]).append(ok)
    if not ok: print('  NO',group,i,str(got)[:70],'ref',str(ref)[:70])
def per(s,a,b): return s.clock.month(a,b)
def rows(s,p,**f): return s._sold(p,None,f)

import collections
print(pd.read_csv('artifacts/norm/public_test/dev_006/sales_pos_chi_tiet_don_lo.csv',dtype=str,nrows=2).T.to_string()[:420])
PL=re.compile(r"\d{2}[A-Za-z]\d?-\d{3}\.?\d{2}")
def rep(s):
    d=s.tables['repairs'].copy();L=s.lines
    d['day']=pd.to_datetime(d.record_date).dt.normalize();d['amt']=pd.to_numeric(d.amount,errors='coerce').fillna(0)
    d['plate']=d['Xe'].astype(str).map(lambda v:(PL.search(v) or [None])[0]);d['dong']=d['Xe'].astype(str).map(lambda v:_folded(PL.sub('',v)))
    names=[str(x) for x in s.tables['staff_danhsachtho_sheet1'].staff]
    last={_folded(n).split()[-1]:n for n in names}
    d['tho']=d.staff.astype(str).map(lambda v:last.get(re.sub(r'^(?:a|anh|chi|c)[\s.]+','',_folded(v)).split()[-1],v))
    d['bh']=d.note.astype(str).map(lambda v:'bao hanh' in _folded(v))
    d['job']=d['Làm gì'].astype(str).map(_folded)
    return d[d.day<=pd.Timestamp(s.clock.as_of)]
pp=lambda d,p:d[(d.day>=pd.Timestamp(p.start))&(d.day<=pd.Timestamp(p.end))]
G='sửa xe'
T(G,'33cb3a',lambda s:len(pp(rep(s),per(s,8,2025))[lambda d:d.tho=='Hà Loan Đạt']),88)
T(G,'827118',lambda s:len(pp(rep(s),per(s,5,2026))[lambda d:d.tho=='Đoàn Bảo Phúc']),115)
T(G,'f3a93a',lambda s:int(pp(rep(s),per(s,7,2026))[lambda d:d.tho=='Hà Loan Đạt'].amt.sum()),23590500)
def rate(s):
    d=s.tables['staff_danhsachtho_sheet1'];return dict(zip(d.staff,pd.to_numeric(d['Hoa hồng (%)'])))
def comm(s,p):
    d=pp(rep(s),p);r=rate(s);g=d.groupby('tho').amt.sum();return {k:int(g[k]*r[k]/100+.5) for k in g.index}
T(G,'027f54',lambda s:comm(s,per(s,8,2025))['Đoàn Bảo Phúc'],8421700)
tb=lambda s,p:sorted(comm(s,p).items(),key=lambda x:-x[1])[0]
T(G,'1c0046',lambda s:list(tb(s,per(s,7,2026))),['Đàm Lan An',9296595]);T(G,'c69505',lambda s:tb(s,per(s,11,2025))[0],'Hà Loan Đạt')
T(G,'20b7bb',lambda s:list(tb(s,per(s,3,2026))),['Đàm Lan An',8001675])
T(G,'a225dc',lambda s:(lambda g:g.index[0])(pp(rep(s),per(s,9,2025)).groupby('tho').day.nunique().sort_values(ascending=False)),'Hà Loan Đạt')
top=lambda s,p:pp(rep(s),p).groupby('tho').amt.sum().sort_values(ascending=False).index[0]
T(G,'b342fe',lambda s:top(s,per(s,4,2026)),'Hà Loan Đạt');T(G,'ad512c',lambda s:top(s,per(s,3,2026)),'Đàm Lan An')
T(G,'32733a',lambda s:pp(rep(s),per(s,10,2025)).groupby('dong').amt.sum().sort_values(ascending=False).index[0],'wave alpha')
pl=lambda s,p,w:pp(rep(s),p)[lambda d:d.dong.str.replace(' ','').str.contains(w)].plate.nunique()
T(G,'5ec780',lambda s:pl(s,per(s,1,2026),'airblade|ab$'),61);T(G,'b6d750',lambda s:pl(s,per(s,12,2025),'wave'),50);T(G,'07e250',lambda s:pl(s,s.clock.this_month(),'shmode|^sh'),27)
def again(s,p): 
    d=pp(rep(s),p);d=d[~d.bh];c=d.groupby('plate').size();return int((c>=2).sum())
T(G,'7f91e4',lambda s:again(s,per(s,10,2025)),33);T(G,'c3158f',lambda s:again(s,s.clock.between('2025-09-01','2025-11-30')),200)
job=lambda s,p,w:len(pp(rep(s),p)[lambda d:(~d.bh)&d.job.str.contains(w)])
d0=rep(shop('4e280a'));print('dong',d0.dong.value_counts().to_dict());print('lap',collections.Counter(t.strip() for v in d0.job for t in v.split('+') if 'lap' in t or 'dau' in t or 'lm' in t).most_common(14))
T(G,'4e280a',lambda s:job(s,per(s,8,2025),'dien'),25);T(G,'7de8d5',lambda s:job(s,per(s,9,2025),'lap'),26);T(G,'c38425',lambda s:job(s,s.clock.this_month(),'va'),98)
bh=lambda s,p:int(pp(rep(s),p).bh.sum())
T(G,'c80365',lambda s:bh(s,s.clock.quarter(2,2026)),39);T(G,'eb6064',lambda s:bh(s,per(s,8,2026)),15)
T(G,'6b5bd6',lambda s:(lambda d:round(100*d.bh.sum()/(~d.bh).sum(),2))(pp(rep(s),s.clock.quarter(4,2025))),2.91)
wd=lambda s,p,k:(lambda d:round(len(d)/d.day.nunique(),2))(pp(rep(s),p)[lambda d:d.day.dt.weekday==k])
T(G,'569dcd',lambda s:wd(s,per(s,3,2026),2),13.5);T(G,'8ce765',lambda s:wd(s,s.clock.this_month(),1),14.0)
avg=lambda s,p:(lambda d:int(d.amt.sum()/(d.amt>0).sum()+.5))(pp(rep(s),p))
T(G,'05cde7',lambda s:avg(s,per(s,2,2026)),226846);T(G,'34a5b4',lambda s:avg(s,per(s,8,2025)),218604);T(G,'ec8d9c',lambda s:avg(s,per(s,1,2026)),234644)

G='lô hạn dùng'
R6='artifacts/norm/public_test/dev_006/'
def lotleft(s,day=None):
    L=pd.Timestamp(day or s.clock.as_of)
    a=pd.read_csv(R6+'purchases_pos_lo_hang.csv',dtype=str);u=pd.read_csv(R6+'sales_pos_chi_tiet_don_lo.csv',dtype=str)
    u=u[pd.to_datetime(u.order_date).dt.normalize()<=L]
    used=pd.to_numeric(u.base_quantity,errors='coerce').groupby(u.lot_id).sum()-pd.to_numeric(u.SLTraQuyDoi,errors='coerce').fillna(0).groupby(u.lot_id).sum()
    c=pd.read_csv(R6+'catalog_pos_san_pham.csv',dtype=str)
    a=a.assign(left=pd.to_numeric(a.SLNhapQuyDoi)-a.lot_id.map(used).fillna(0),exp=pd.to_datetime(a.expiry_date),cost=pd.to_numeric(a.unit_cost));a['name']=a.item_code.map(c.set_index('item_code').item_name)
    return a[a.left>0]
def win(s,n=None,a=None,b=None):
    D=pd.Timestamp(a or s.clock.as_of);E=pd.Timestamp(b) if b else D+pd.Timedelta(days=n);x=lotleft(s);return x[(x.exp>=D)&(x.exp<=E)]
T(G,'fb4094',lambda s:len(win(s,120)),14);T(G,'c3439f',lambda s:int((win(s,180).left*win(s,180).cost).sum()),12913800);T(G,'393267',lambda s:int((lambda x:(x.left*x.cost).sum())(win(s,a='2026-08-08',b='2026-12-06'))),7891700)
first=lambda s,n:(lambda x:x[x.name.astype(str).str.contains(n,regex=False)&(x.exp>=pd.Timestamp(s.clock.as_of))].exp.min().strftime('%Y-%m-%d'))(lotleft(s))
T(G,'210d0c',lambda s:first(s,'Berocca Performance'),'2028-01-16');T(G,'411cb8',lambda s:first(s,'Oresol 245'),'2026-12-02');T(G,'481401',lambda s:first(s,'Augmentin 625mg'),'2027-01-17')
def lst(s,x):
    g=x.sort_values(['exp','item_code']).drop_duplicates('item_code');return g.name.tolist()
Rf={json.loads(l)['id'][2:8]:json.loads(l) for l in open('experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl')}
T(G,'0ca19c',lambda s:lst(s,win(s,90)),Rf['0ca19c']['answer']);T(G,'6c4f54',lambda s:lst(s,win(s,a='2026-08-08',b='2027-01-05')),Rf['6c4f54']['answer'])
oos=lambda s,d=None:int((s._stock_levels(d).iloc[:,-1]<=0).sum()) if False else None
def stockout(s,d=None):
    L=pd.Timestamp(d or s.clock.as_of);t=pd.read_csv(R6+'inventory_pos_the_kho.csv',dtype=str);t=t[pd.to_datetime(t.NgayGioPhatSinh)<pd.Timedelta(days=1)+L];q=pd.to_numeric(t.base_quantity).groupby(t.item_code).sum();return int((q<=0).sum())
T(G,'4d20e3',stockout,1);T(G,'b01bee',stockout,1);T(G,'c1a3be',lambda s:stockout(s,'2025-06-01'),2)
G='từ rulebook'
def rk(s,p,key,fn):
    l=s._sold(p,None,{});return fn(l)
def sop(s,p):
    o=s.sold_orders(p);o=o[o.customer_key.notna()];g=o.groupby('customer_key').revenue.agg(['sum','count']);g=g[g['count']>=3];g['avg']=g['sum']/g['count'];return g.assign(k=g.index).sort_values(['avg','k'],ascending=[False,True]).index[0]
nm=lambda s,k:(lambda o:o[o.customer_key==k].customer_name.iloc[0])(s.orders)
T(G,'9d8949',lambda s:nm(s,sop(s,per(s,5,2026))),'Hồ Cường Hùng')
def doiy(s,p):
    o=s.orders;d=pd.to_datetime(o.order_date).dt.normalize();o=o[(d>=pd.Timestamp(p.start))&(d<=pd.Timestamp(p.end))&(o.status_norm=='huỷ')&o.customer_key.notna()];g=o.groupby('customer_key').size();return pd.DataFrame({'v':g,'k':g.index}).sort_values(['v','k'],ascending=[False,True]).index[0]
T(G,'b38db1',lambda s:doiy(s,s.clock.quarter(3,2025)),'KH0108')
T(G,'a7dd46',lambda s:s.ranking(by='item',metric='orders',period=per(s,7,2025)).index[0],'Rau muống xào tỏi')
T(G,'3f61cd',lambda s:s.ranking(by='day',metric='orders',period=per(s,8,2025)).index[0],'2025-08-02')
def loyal(s,p):
    l=s._sold(p,None,{});l=l[l.customer_key.notna()];g=l.groupby('customer_key').order_date.apply(lambda v:pd.to_datetime(v).dt.normalize().nunique());k=pd.DataFrame({'v':g,'k':g.index}).sort_values(['v','k'],ascending=[False,True]).index[0];return l[l.customer_key==k].customer_name.iloc[0]
T(G,'735ea0',lambda s:loyal(s,per(s,3,2025)),'Giang Phương Hùng')
T(G,'203767',lambda s:int(s._sold(per(s,3,2026),None,{}).groupby('hour').order_id.nunique().sort_values(ascending=False).index[0]),8)
def mainsup(s,p):
    r=s._purchase_lines();r=r[(r.day>=pd.Timestamp(p.start))&(r.day<=pd.Timestamp(p.end))];g=r.groupby('supplier').document_id.nunique();return pd.DataFrame({'v':g,'k':g.index}).sort_values(['v','k'],ascending=[False,True]).index[0]
T(G,'08b923',lambda s:mainsup(s,per(s,12,2025)),'Cty Mai Hải')
T(G,'d54752',lambda s:s.ranking(by='staff',period=per(s,1,2026)).index[0],'NV002')
G='đổi giá'
def raise_day(s,item,price):
    code=None
    for n,f in s.tables.items():
        if n.startswith('catalog') and ('Giá mới' in f.columns or 'NgayApDung' in f.columns):
            f=f.copy()
            if 'NgayApDung' in f:
                c=next(x for k,x in s.tables.items() if k.startswith('catalog') and {'item_code','item_name'}<=set(x.columns));f['item_name']=f.item_code.map(c.set_index('item_code').item_name);col,day='unit_price','NgayApDung'
            else: col,day='Giá mới','Ngày áp dụng'
            g=f[f.item_name.astype(str).map(_folded)==_folded(item)].assign(p=lambda d:pd.to_numeric(d[col],errors='coerce'),d=lambda d:pd.to_datetime(d[day])).sort_values('d')
            up=g[(g.p==price)&(g.p>g.p.shift())]
            return up.d.iloc[0].strftime('%Y-%m-%d')
T(G,'501cc0',lambda s:s.price_effect('Acyclovir Stella kem 5% tuýp 5g',raise_day(s,'Acyclovir Stella kem 5% tuýp 5g',18000),days=30),-50.0)
T(G,'5e7b3b',lambda s:s.price_effect('Hapacol 250 hộp 24 gói',raise_day(s,'Hapacol 250 hộp 24 gói',2100),days=7),-41.08)
T(G,'8c88fc',lambda s:s.price_effect('Phosphalugel hộp 26 gói',raise_day(s,'Phosphalugel hộp 26 gói',5400),days=30),-41.61)
T(G,'45d6cb',lambda s:s.price_effect('Trà vải (L)',raise_day(s,'Trà vải (L)',47000),days=30),-3.6)
T(G,'c810dc',lambda s:s.price_effect('Topping Thạch cà phê',raise_day(s,'Topping Thạch cà phê',7400),days=30),8.6)
T(G,'dd2362',lambda s:s.price_effect('Bạc xỉu (M)',raise_day(s,'Bạc xỉu (M)',35000),days=14),-9.24)
T(G,'18d3b1',lambda s:s.price_effect('Tiffy Dey hộp 25 vỉ x 4 viên','2025-06-02',days=14),-33.51)
T(G,'378a68',lambda s:s.price_effect('Tiffy Dey hộp 25 vỉ x 4 viên','2025-10-16',days=30),-5.4)
s=shop('18d3b1');print('Tiffy names',sorted(n for n in s.lines.item_name.dropna().unique() if 'Tiffy' in n));
x=s.lines[s.lines.item_name.astype(str).str.contains('Tiffy')];print(x[['item_name','unit','quantity','base_quantity']].drop_duplicates().head(6).to_string())
for k,v in res.items(): print(f'{k:18s} {sum(v)}/{len(v)}')
