import json,re,sys,glob,warnings;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
import pandas as pd
from datamate.shop import Shop,_folded
from datamate.norm import parse_datetime
from datamate_agent.intents import period_of
Q={json.loads(l)['id']:json.loads(l) for l in open('train/questions.jsonl')};G={json.loads(l)['id']:json.loads(l) for l in open('train/answers.jsonl')}
def sh(q): return Shop(f"artifacts/norm/train/{q['business_id']}",as_of=q['as_of_date'],calendar='train/calendar.csv')
def per(s,q):
    code=period_of(q['question'])
    return eval(code,{'clock':s.clock}) if code else None
tally={}
def rec(g,i,got):
    a=G[i].get('answer');ok=got==a or (G[i]['type']=='unanswerable' and got is None)
    tally.setdefault(g,[]).append(ok);print(('OK ' if ok else 'NO '),g,Q[i]['business_id'],i[2:8],Q[i]['question'][:62],'| got',str(got)[:34],'| gold',G[i]['type'],str(a)[:34])
# delivery
for i,q in Q.items():
    if re.search(r'đợt',q['question'].lower()) and q['business_id'] in('biz_117','biz_118'):
        s=sh(q);p=per(s,q);t=[f for n,f in s.tables.items() if 'Lượt giao' in f.columns]
        if not t: rec('đợt giao',i,'no column');continue
        d=t[0];day=pd.to_datetime(d['Thời gian giao'].map(parse_datetime),errors='coerce').dt.normalize();d=d[(day>=pd.Timestamp(p.start))&(day<=pd.Timestamp(p.end))]
        rec('đợt giao',i,d[['order_id','Lượt giao']].drop_duplicates().shape[0])
# lots biz_123 pos
def lots(root,as_of):
    a=pd.read_csv(root+'/purchases_pos_lo_hang.csv',dtype=str);u=pd.read_csv(root+'/sales_pos_chi_tiet_don_lo.csv',dtype=str);u=u[pd.to_datetime(u.order_date).dt.normalize()<=pd.Timestamp(as_of)]
    used=pd.to_numeric(u.base_quantity,errors='coerce').groupby(u.lot_id).sum()-pd.to_numeric(u.SLTraQuyDoi,errors='coerce').fillna(0).groupby(u.lot_id).sum()
    c=pd.read_csv(root+'/catalog_pos_san_pham.csv',dtype=str)
    a=a.assign(left=pd.to_numeric(a.SLNhapQuyDoi)-a.lot_id.map(used).fillna(0),exp=pd.to_datetime(a.expiry_date),cost=pd.to_numeric(a.unit_cost));a['name']=a.item_code.map(c.set_index('item_code').item_name);return a[a.left>0]
for i,q in Q.items():
    if q['business_id']!='biz_123' or not re.search(r'hạn dùng|\blô\b|hết hạn',q['question'].lower()):continue
    r=f"artifacts/norm/train/biz_123";x=lots(r,q['as_of_date']);D=pd.Timestamp(q['as_of_date']);t=q['question'].lower()
    ds=re.findall(r'(\d{2})/(\d{2})/(\d{4})',t);w=None
    if len(ds)==2:
        a,b=[pd.Timestamp(int(y),int(m),int(d_)) for d_,m,y in ds];w=x[(x.exp>=a)&(x.exp<=b)]
    if 'gần hết hạn' in t:
        hit=[n for n in x.name.dropna().unique() if _folded(n).split(' ')[0] in _folded(t)]
        best=[n for n in hit if _folded(n) in _folded(t)]
        rec('lô',i,x[(x.name.isin(best))&(x.exp>=D)].exp.min().strftime('%Y-%m-%d') if best else 'no item')
    elif 'tiền vốn' in t: rec('lô',i,int((w.left*w.cost).sum()))
    elif 'hàng nào' in t: rec('lô',i,w.sort_values(['exp','item_code']).drop_duplicates('item_code').name.tolist())
    else: rec('lô',i,len(w) if w is not None else 'skip')
for k,v in tally.items(): print(k,sum(v),'/',len(v))
