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
    d['tho']=d.staff.astype(str).map(lambda v:last.get(_folded(v).split()[-1],v))
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
print('jobs',collections.Counter(t.strip() for v in rep(shop('4e280a')).job for t in v.split('+')).most_common(50))
T(G,'4e280a',lambda s:job(s,per(s,8,2025),'dien'),25);T(G,'7de8d5',lambda s:job(s,per(s,9,2025),'lap'),26);T(G,'c38425',lambda s:job(s,s.clock.this_month(),'va'),98)
bh=lambda s,p:int(pp(rep(s),p).bh.sum())
T(G,'c80365',lambda s:bh(s,s.clock.quarter(2,2026)),39);T(G,'eb6064',lambda s:bh(s,per(s,8,2026)),15)
T(G,'6b5bd6',lambda s:(lambda d:round(100*d.bh.sum()/(~d.bh).sum(),2))(pp(rep(s),s.clock.quarter(4,2025))),2.91)
wd=lambda s,p,k:(lambda d:round(len(d)/d.day.nunique(),2))(pp(rep(s),p)[lambda d:d.day.dt.weekday==k])
T(G,'569dcd',lambda s:wd(s,per(s,3,2026),2),13.5);T(G,'8ce765',lambda s:wd(s,s.clock.this_month(),1),14.0)
avg=lambda s,p:(lambda d:int(d.amt.sum()/(d.amt>0).sum()+.5))(pp(rep(s),p))
T(G,'05cde7',lambda s:avg(s,per(s,2,2026)),226846);T(G,'34a5b4',lambda s:avg(s,per(s,8,2025)),218604);T(G,'ec8d9c',lambda s:avg(s,per(s,1,2026)),234644)
G='đợt giao'
def dl(s):
    d=s.tables['sales_sogiaohang_sheet1'].copy();d['day']=pd.to_datetime(d['Thời gian giao'].map(parse_datetime),errors='coerce').dt.normalize();return d[d.day<=pd.Timestamp(s.clock.as_of)]
trips=lambda s,p:pp(dl(s),p)[['order_id','Lượt giao']].drop_duplicates().shape[0]
T(G,'ae7e44',lambda s:trips(s,s.clock.this_month()),249);T(G,'c78fdf',lambda s:trips(s,per(s,7,2025)),792);T(G,'c8fde5',lambda s:trips(s,per(s,11,2025)),671)
def multi(s,m,y):
    d=dl(s);d=d[pd.to_datetime(d.order_date).dt.to_period('M')==f'{y}-{m:02d}'];return int((d.groupby('order_id')['Lượt giao'].nunique()>=2).sum())
T(G,'7be693',lambda s:multi(s,6,2025),96);T(G,'5c6817',lambda s:multi(s,11,2025),105);T(G,'936c6e',lambda s:multi(s,3,2026),106)
def shipped(s,m,y,n,big):
    d=dl(s);d=d[(pd.to_datetime(d.order_date).dt.to_period('M')==f'{y}-{m:02d}')&(d.item_name==n)];return pd.to_numeric(d.base_quantity).sum()/big
T(G,'59f279',lambda s:shipped(s,4,2025,'Dây điện Cadivi VCmd 2x2.5 cuộn 100m',1),37);T(G,'76edb5',lambda s:shipped(s,3,2026,'Sơn Dulux Weathershield Powerflexx 5L',1),23);T(G,'cf2c96',lambda s:shipped(s,5,2025,'Gạch ốp tường Viglacera 30x60 thùng 8 viên',1),39)
G='ngày phải trả'
T(G,'10831a',lambda s:s.due_orders(after=s.clock.as_of),152);T(G,'1adddf',lambda s:s.due_orders(after=s.clock.as_of),145);T(G,'9eddae',lambda s:s.due_orders(after=s.clock.as_of),164)
T(G,'7305db',lambda s:s.due_orders(per(s,4,2026)),19);T(G,'af96aa',lambda s:s.due_orders(per(s,2,2026)),35);T(G,'a18fef',lambda s:s.due_orders(per(s,11,2025)),21)
G='mẹ và bé'
def fee(s,p,w):
    l=s._rows();l=l[l.status_norm.astype(str).map(lambda v:v not in('huỷ','trả hàng'))];d=l.assign(day=pd.to_datetime(l.order_date).dt.normalize());d=pp(d,p);return int(abs(pd.to_numeric(d[d.item_name.astype(str).map(_folded).str.contains(w)].line_amount).sum()))
for i,f,w,r in [('5cd8a3',(12,2025),'voucher',5880000),('1c7bef',(6,2026),'voucher',5500000),('4497ce',(5,2026),'phi ship',4825000),('5355ac',(6,2026),'phi ship',4350000),('dbb9f4',(6,2026),'diem',2220000)]: T(G,i,lambda s,f=f,w=w:fee(s,per(s,*f),w),r)
T(G,'77c325',lambda s:fee(s,s.clock.this_month(),'voucher'),2900000);T(G,'dae195',lambda s:fee(s,s.clock.this_month(),'phi ship'),2125000)
def cat(s,p,col,val,grp='bỉm tã'):
    c=s.tables['catalog_quanly_danhmuc'];m=c.set_index('item_name')
    l=s._sold(p,None,{});l=l.assign(g=l.item_name.map(m.item_group),v=l.item_name.map(m[col]))
    a=l[l.g==grp];return a[a.v==val].base_quantity.sum(),a.base_quantity.sum(),a
sz='Số / Size'
T(G,'b362a4',lambda s:cat(s,per(s,5,2026),sz,'Size M')[0],153);T(G,'78f694',lambda s:cat(s,s.clock.this_month(),sz,'Size L')[0],166)
ps=lambda t:round(100*t[0]/t[1],2)
T(G,'ed68b2',lambda s:ps(cat(s,s.clock.this_month(),sz,'Size M')),31.32);T(G,'94a2e7',lambda s:ps(cat(s,s.clock.this_month(),sz,'Size XL')),16.11);T(G,'95f39e',lambda s:ps(cat(s,per(s,1,2026),sz,'Size NB')),15.87)
T(G,'7d236c',lambda s:ps(cat(s,s.clock.this_month(),'Hãng','Bobby')),36.47);T(G,'ab0d15',lambda s:ps(cat(s,s.clock.this_month(),'Hãng','Moony')),5.15);T(G,'dcd34f',lambda s:ps(cat(s,per(s,2,2026),'Hãng','Huggies')),29.25)
T(G,'1fc800',lambda s:cat(s,s.clock.this_month(),sz,'Số 4','sữa bột')[0],44);T(G,'24a84f',lambda s:cat(s,s.clock.this_month(),sz,'Số 2','sữa bột')[0],75)
T(G,'14a10f',lambda s:(lambda a:a[a.v=='Số 2'].assign(h=lambda d:d.item_name.map(s.tables['catalog_quanly_danhmuc'].set_index('item_name')['Hãng'])).groupby('h').base_quantity.sum().sort_values(ascending=False).index[0])(cat(s,per(s,3,2026),sz,'Số 2','sữa bột')[2]),'Vinamilk')
T(G,'e36c0b',lambda s:(lambda d:int(((d>=pd.Timestamp('2026-05-01'))&(d<=pd.Timestamp('2026-05-31'))).sum()))(pd.to_datetime(s.tables['customers_quanly_khachhang']['Ngày đăng ký'],errors='coerce')),15)
G='lô hạn dùng'
def lots(s):
    r='artifacts/norm/public_test/dev_006/';a=pd.read_csv(r+'purchases_pos_lo_hang.csv',dtype=str);u=pd.read_csv(r+'sales_pos_chi_tiet_don_lo.csv',dtype=str)
    return a,u
print('lo cols',list(lots(shop('fb4094'))[1].columns))
for k,v in res.items(): print(f'{k:18s} {sum(v)}/{len(v)}')
