import openpyxl, re, datetime as dt, collections
D='/Users/lebahoai/Workspace/zalo/2026/public_test/data/dev_013/'
def money(v):
    if isinstance(v,(int,float)): return float(v)
    s=str(v).strip().replace('đ','')
    if s.endswith('tr'): return float(s[:-2].replace(',','.'))*1e6
    return float(s.replace('.',''))
def pdate(v,y):
    if isinstance(v,dt.datetime): return v.date()
    if isinstance(v,(int,float)): return (dt.datetime(1899,12,30)+dt.timedelta(days=v)).date()
    s=str(v).strip()
    m=re.match(r'(\d+) thg (\d+) (\d+)$',s)
    if m: return dt.date(int(m[3]),int(m[2]),int(m[1]))
    p=s.split('/')
    if len(p)==2: return dt.date(y,int(p[1]),int(p[0]))
    return dt.date(int(p[2]),int(p[1]),int(p[0]))
rows=[]
for f in ['BanHang_2025.xlsx','BanHang_2026.xlsx']:
    wb=openpyxl.load_workbook(D+f,read_only=True)
    for ws in wb.worksheets:
        y=int(ws.title[-4:]); seen=set()
        for r in list(ws.iter_rows(values_only=True))[2:]:
            r=tuple(r)+(None,)*(10-len(r)); r=r[:10]
            if r[5] is None: continue
            if r in seen: continue
            seen.add(r); rows.append((y,)+tuple(r))
orders=collections.defaultdict(lambda: {'items':[], 'adj':[], 'date':None,'note':'','cust':None,'ch':None})
for y,dg,tt,sl,dvt,name,hd,ngay,kh,kenh,gc in rows:
    o=orders[hd]
    if sl is None: o['adj'].append((name,money(tt)))
    else:
        o['items'].append((name,money(tt),sl,dvt)); o['date']=pdate(ngay,y); o['cust']=kh; o['ch']=kenh
        if gc: o['note']=str(gc).lower()
good={h:o for h,o in orders.items() if o['note'] not in ('huỷ','cancel')}
def inm(o,y,m): return o['date'].year==y and o['date'].month==m
jun=[o for o in good.values() if inm(o,2026,6)]
rev=sum(t for o in jun for _,t,_,_ in o['items'])
print('V1 rev 2026-06', rev)
print('V2 voucher 2026-06', -sum(t for o in jun for n,t in o['adj'] if n=='Voucher'))
print('V3 AOV 2026-06', rev/len(jun), len(jun))
print('V4 orders>=450k 2026-06', sum(1 for o in jun if sum(t for _,t,_,_ in o['items'])>=450000))
print('V5 points 2026-06', -sum(t for o in jun for n,t in o['adj'] if n.startswith('Dùng')))
print('V6 ship 2026-05', sum(t for o in good.values() if inm(o,2026,5) for n,t in o['adj'] if n=='Phí ship'))
wb=openpyxl.load_workbook(D+'QuanLy.xlsx',read_only=True)
kh=list(wb['KhachHang'].iter_rows(values_only=True))[1:]
print('V7 new members 2026-05', sum(1 for r in kh if r[3].year==2026 and r[3].month==5))
dm=list(wb['DanhMuc'].iter_rows(values_only=True))[1:]
info={r[0]:r for r in dm}
def base(name,dvt,sl):
    r=info[name]
    if dvt==r[5]: return sl
    m=re.search(r'1 '+dvt+r' = (\d+)', r[6] or ''); return sl*int(m[1])
tot=0; sz=collections.Counter(); br=collections.Counter()
for o in jun:
    for n,t,sl,dvt in o['items']:
        r=info[n]
        if r[2]=='bỉm tã':
            q=base(n,dvt,sl); tot+=q; sz[r[4]]+=q; br[r[3]]+=q
print('V8 diaper June total', tot, {k:round(100*v/tot,2) for k,v in sz.items()}, {k:round(100*v/tot,2) for k,v in br.items()})
def cheese(a,b):
    return sum(base(n,dvt,sl) for o in good.values() if a<=o['date']<=b for n,t,sl,dvt in o['items'] if n.startswith('Phô mai'))
after=cheese(dt.date(2025,6,7),dt.date(2025,7,6)); before=cheese(dt.date(2025,5,8),dt.date(2025,6,6))
print('V9 cheese', after, before, round(100*(after-before)/before,2))
prices=collections.Counter((o['date']>=dt.date(2025,6,7), money(None) if False else None) for o in [])
pr=collections.defaultdict(set)
for y,dg,tt,sl,dvt,name,hd,ngay,kh_,kenh,gc in rows:
    if name and str(name).startswith('Phô mai') and dvt=='hộp':
        d=pdate(ngay,y)
        if dt.date(2025,5,25)<=d<=dt.date(2025,6,20): pr[d].add(money(dg))
print('cheese price by date', sorted((k.isoformat(),sorted(v)) for k,v in pr.items()))
