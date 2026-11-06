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
# ---- phone: order level
def orders_rev(s,p):
    l=s._sold(p,None,{});return l.drop_duplicates('order_id')
def tradein14(s,p):
    t=s.tables['customers_thumaycu_sheet1'].copy();ok=set(orders_rev(s,p).order_id.astype(str).str.replace('.0','',regex=False))
    t['oid']=t['Trừ vào (STT sổ bán)'].astype(str).str.replace('.0','',regex=False);return int(pd.to_numeric(t[t.oid.isin(ok)].amount).sum())
def tradein11(s,p):
    o=orders_rev(s,p);return int(o['Thu máy cũ'].map(lambda v:parse_money(v,default=0) or 0).sum())
def payable(s,p):
    return int(orders_rev(s,p).paid_amount.map(lambda v:parse_money(v,default=0) or 0).sum())
def payable_avg(s,p):
    o=orders_rev(s,p);return int(payable(s,p)/len(o)+.5)
def machines(s,p,groups=('máy mới','máy cũ')):
    l=rows(s,p);return l[l.item_group.isin(groups)]
def dong(n):
    m=re.match(r'^(.*?)\s+\d+\s*GB',str(n),flags=re.I);return m.group(1).strip() if m else str(n)
def brand(n):
    w=str(n).split()[0];return 'Apple' if w.lower()=='iphone' else w
def qty(x): return int(x.quantity.sum())
for i,a,y,r in [('8cb214',5,2026,94),('a29355',6,2025,82),('d99e83',7,2025,82),('3fb7bb',8,2025,167)]: T('máy',i,lambda s,a=a,y=y:qty(machines(s,per(s,a,y))),r)
T('máy','97a88c',lambda s:qty(machines(s,s.clock.this_month(),('máy cũ',))),26)
for i,n,p,r in [('8a1878','Samsung Galaxy A56 5G',(6,2026),6),('e4fc0d','Xiaomi Redmi Note 14',(1,2026),11)]:
    T('máy',i,lambda s,n=n,p=p:qty(machines(s,per(s,*p))[lambda d:d.item_name.map(dong)==n]),r)
T('máy','d622b7',lambda s:qty(machines(s,s.clock.this_month())[lambda d:d.item_name.map(dong)=='iPhone 16 Pro Max']),7)
T('máy','12712b',lambda s:qty(machines(s,s.clock.this_month())[lambda d:d.item_name.map(dong)=='Xiaomi Redmi Note 14']),6)
def avgm(s,p):
    m=machines(s,p);return int(m.line_amount.sum()/m.quantity.sum()+.5)
T('máy','d08785',lambda s:avgm(s,per(s,12,2025)),11025908);T('máy','8e50e2',lambda s:avgm(s,s.clock.this_month()),9563422)
def topdong(s,p,k):
    m=machines(s,p);g=m.groupby(m.item_name.map(dong)).quantity.sum();return pd.DataFrame({'v':g,'k':g.index}).sort_values(['v','k'],ascending=[False,True]).index[:k].tolist()
T('máy','473593',lambda s:topdong(s,s.clock.quarter(1,2026),3),["Xiaomi Redmi Note 14","iPhone 16","iPhone 16 Pro Max"]);T('máy','7826ef',lambda s:topdong(s,per(s,1,2026),3),["iPhone 16 Pro Max","iPhone 15","Xiaomi Redmi Note 14"])
T('máy','792e10',lambda s:(lambda m:round(100*m[m.item_name.map(brand)=='Samsung'].quantity.sum()/m.quantity.sum(),2))(machines(s,per(s,10,2025))),27.82)
share=lambda m:round(100*m[m.item_group=='máy mới'].line_amount.sum()/m.line_amount.sum(),2)
T('máy','3ac94b',lambda s:share(machines(s,per(s,4,2026))),77.26);T('máy','4b82c6',lambda s:share(machines(s,s.clock.this_month())),78.49)
for i,p,r in [('101906',(2,2026),54100000),('86a32a',(8,2025),117000000),('0b8546',(9,2025),36300000)]: T('thu máy cũ',i,lambda s,p=p:tradein14(s,per(s,*p)),r)
for i,p,r in [('650a53',(6,2025),31100000),('701bf3',(11,2025),49300000)]: T('thu máy cũ',i,lambda s,p=p:tradein11(s,per(s,*p)),r)
T('thu máy cũ','104054',lambda s:tradein11(s,s.clock.this_month()),55500000)
for i,p,r in [('5bfa54',(6,2025),871448000),('edce3c',(12,2025),1260328000),('4c24ac',(2,2026),1706335000),('763243',(12,2025),1546763000)]: T('khách phải trả',i,lambda s,p=p:payable(s,per(s,*p)),r)
T('khách phải trả','8db0ee',lambda s:payable(s,s.clock.this_month()),926729000);T('khách phải trả','78b9ca',lambda s:payable(s,s.clock.this_month()),1564120000)
for i,p,r in [('94f634',(8,2025),4325306),('e0ac21',(6,2026),4259801),('f30748',(8,2026),3702376)]: T('khách phải trả',i,lambda s,p=p:payable_avg(s,per(s,*p)),r)
def share_ti(s,p):
    o=orders_rev(s,p);t=s.tables['customers_thumaycu_sheet1'];ids=set(t['Trừ vào (STT sổ bán)'].astype(str).str.replace('.0','',regex=False));return round(100*o.order_id.astype(str).str.replace('.0','',regex=False).isin(ids).sum()/len(o),2)
T('thu máy cũ','3a9665',lambda s:share_ti(s,per(s,4,2026)),4.6);T('thu máy cũ','603c21',lambda s:share_ti(s,s.clock.this_month()),3.81)
# warranty
def wr(s): 
    d=s.tables['catalog_sono_bao_hanh'];return d.assign(day=pd.to_datetime(d.record_date))
def inp(d,p): return d[(d.day>=pd.Timestamp(p.start))&(d.day<=pd.Timestamp(p.end))]
T('bảo hành','5a9e0b',lambda s:len(inp(wr(s),s.clock.quarter(1,2026))),47);T('bảo hành','a883b3',lambda s:len(inp(wr(s),s.clock.quarter(4,2025))),31)
T('bảo hành','25af2e',lambda s:round(100*len(inp(wr(s),s.clock.quarter(3,2026)))/qty(machines(s,s.clock.quarter(3,2026))),2),13.08)
def wrsold(s,p):
    m=machines(s,p);imeis=set(x.strip() for v in m.IMEI.dropna() for x in str(v).split('/'));w=wr(s);return int(sum(i in set(w.IMEI.astype(str).str.strip()) for i in imeis))
T('bảo hành','b2eb16',lambda s:wrsold(s,per(s,7,2026)),5);T('bảo hành','7c8c12',lambda s:wrsold(s,per(s,8,2025)),5)
T('bảo hành','917d6a',lambda s:inp(wr(s),s.clock.quarter(2,2026)).item_name.value_counts().index[0],'Xiaomi Redmi Note 14')
# installment
def inst(s):
    d=s.tables['sales_sono_tra_gop'].copy();cols=['order_id','order_date','customer_name','unit_price','Trả trước','Số kỳ','Góp/tháng','Hạn góp (ngày)']
    d[cols]=d[cols].ffill() if False else d[cols]
    return d
def contracts(s,limit):
    raw=s.tables.__class__
    d=pd.read_csv(s.root+'/sales_sono_tra_gop.csv',dtype=str)
    out=[]
    for oid,g in d.groupby('order_id',sort=False):
        h=g.iloc[0];day=pd.to_datetime(h.order_date)
        if day>limit: continue
        price=parse_money(h.unit_price,default=0) or 0;pre=parse_money(h['Trả trước'],default=0) or 0
        n=int(float(h['Số kỳ']));mon=parse_money(h['Góp/tháng'],default=0) or 0;dd=int(float(h['Hạn góp (ngày)']))
        paid=0
        for a,b in zip(g['Ngày góp'],g['Đã góp']):
            t=parse_datetime(a)
            if t is not None and pd.Timestamp(t)<=limit: paid+=parse_money(b,default=0) or 0
        dues=[]
        for k in range(1,n+1):
            y=day.year+(day.month-1+k)//12;m=(day.month-1+k)%12+1
            dues.append(pd.Timestamp(y,m,min(dd,pd.Period(f'{y}-{m}').days_in_month)))
        out.append(dict(oid=oid,day=day,cust=h.customer_name,price=price,pre=pre,n=n,mon=mon,paid=paid,dues=dues,left=price-pre-paid))
    return out
import types
for k,v in list(C.items()): pass
def lim(s,x=None): return pd.Timestamp(x) if x else pd.Timestamp(s.clock.as_of)
def setroot(i):
    s=shop(i);s.root=f"artifacts/norm/public_test/{Q[i]['business_id']}";return s
for i in ('059458','51b4d4','435a38','5c0aca','e734e6','101a2b','8e44f6','16852a','338d01','527c4e','a8d7ce','b33016','6d42e3','e2ad9e','ff9f21','f37ffc'): setroot(i)
remain=lambda s,x=None:int(sum(c['left'] for c in contracts(s,lim(s,x))))
T('trả góp','059458',remain,400700000);T('trả góp','51b4d4',remain,314300000)
cust=lambda s,n,x=None:int(sum(c['left'] for c in contracts(s,lim(s,x)) if n in str(c['cust'])))
T('trả góp','435a38',lambda s:cust(s,'Ông Hiếu Anh'),900000);T('trả góp','5c0aca',lambda s:cust(s,'Ngô Nam Ngân'),24000000);T('trả góp','e734e6',lambda s:cust(s,'Lương Khoa Hoàng'),900000)
due_n=lambda s,n:sum(sum(d<=lim(s) for d in c['dues']) for c in contracts(s,lim(s)) if n in str(c['cust']))
T('trả góp','101a2b',lambda s:due_n(s,'Tạ Dũng Long'),4);T('trả góp','8e44f6',lambda s:due_n(s,'Triệu Thu Trang'),3)
def overdue(s,x):
    L=lim(s,x);return [ (c,max(0,sum(d<L for d in c['dues'])*c['mon']-c['paid'])) for c in contracts(s,L)]
T('trả góp','16852a',lambda s:len({c['cust'] for c,v in overdue(s,'2026-03-13') if v>0}),16);T('trả góp','338d01',lambda s:len({c['cust'] for c,v in overdue(s,'2026-02-08') if v>0}),6);T('trả góp','527c4e',lambda s:len({c['cust'] for c,v in overdue(s,'2026-09-02') if v>0}),17)
T('trả góp','a8d7ce',lambda s:int(sum(v for c,v in overdue(s,'2025-11-26'))),28600000);T('trả góp','b33016',lambda s:int(sum(v for c,v in overdue(s,None))),20000000);T('trả góp','6d42e3',lambda s:int(sum(v for c,v in overdue(s,'2026-06-01'))),40200000)
def book(s,L):
    d=pd.read_csv(s.root+'/customers_sono_so_no.csv',dtype=str);d['oid']=d.note;out=[]
    for oid,g in d.groupby('oid',sort=False):
        h=g.iloc[0];day=pd.to_datetime(h.record_date)
        if day>L: continue
        p=sum((parse_money(a,default=0) or 0) for a,t in zip(g.paid_amount,g['Ngày trả']) if parse_datetime(t) is not None and pd.Timestamp(parse_datetime(t))<=L)
        out.append(dict(cust=h.customer_name,day=day,left=(parse_money(h.debt_amount,default=0) or 0)-p))
    return out
def total(s,x):
    L=lim(s,x);return [ (b['cust'],b['day'],b['left']) for b in book(s,L) if b['left']>0]+[(c['cust'],c['day'],c['left']) for c in contracts(s,L) if c['left']>0]
T('sổ nợ','e2ad9e',lambda s:int(sum(v for _,_,v in total(s,'2026-09-27'))),825818668);T('sổ nợ','ff9f21',lambda s:len({c for c,_,_ in total(s,'2026-06-02')}),115)
def ages(s,x):
    L=lim(s,x);a=[0,0,0]
    for _,d,v in total(s,x):
        g=(L-d).days;a[0 if g<=7 else 1 if g<=15 else 2]+=v
    return [int(x) for x in a]
T('sổ nợ','f37ffc',lambda s:ages(s,'2026-09-23'),[30052000,29811500,785559168])
for k,v in res.items(): print(f'{k:18s} {sum(v)}/{len(v)}')
