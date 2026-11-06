import json,re,sys,glob,os,collections,warnings;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
import pandas as pd
from datamate.shop import Shop
from datamate_agent.intents import period_of
from datamate_agent.question_norm import normalize
TQ={json.loads(l)['id']:json.loads(l) for l in open('train/split/train_questions.jsonl',encoding='utf-8')}
G={json.loads(l)['id']:json.loads(l) for l in open('train/split/train_answers.jsonl',encoding='utf-8')}
cache={}
def shop(q):
    k=(q['business_id'],q['as_of_date'])
    if k not in cache: cache[k]=Shop(f"artifacts/norm/train/{q['business_id']}",as_of=q['as_of_date'],calendar='train/calendar.csv')
    return cache[k]
out=tp=fp=fn=0;cases=[]
unans=[i for i in TQ if G[i]['type']=='unanswerable']
print('gold unanswerable train_',len(unans),'/',len(TQ))
for i,q in TQ.items():
    s=shop(q)
    if s.lines is None: continue
    code=period_of(normalize(q['question']))
    if not code or 'month' not in code and 'quarter' not in code: 
        if G[i]['type']=='unanswerable': fn+=1
        continue
    p=eval(code,{'clock':s.clock})
    days=pd.to_datetime(s.lines.order_date).dt.normalize();lo,hi=days.min(),days.max()
    outside=pd.Timestamp(p.end)<lo or pd.Timestamp(p.start)>hi
    if outside and G[i]['type']=='unanswerable': tp+=1
    elif outside: fp+=1;cases.append((q['business_id'],q['question'][:60],G[i]['type'],str(G[i].get('answer'))[:20],str(p.start),str(lo)[:10]))
    elif G[i]['type']=='unanswerable': fn+=1
print('kỳ ngoài dữ liệu: đúng',tp,'báo nhầm',fp,'unanswerable còn lại',fn);print(cases[:8])
words=collections.Counter()
for i in unans:
    words[re.sub(r'\d+','#',normalize(TQ[i]['question']))[:60]]+=1
print(words.most_common(30))
print('--- percent bug')
pr=re.compile(r'%|phan tram|phần trăm')
n=sum(1 for i,q in TQ.items() if '%' in q['question'] and G[i]['type']!='percent');print('câu có % trong câu mà gold không phải percent',n)
PQ=[json.loads(l) for l in open('public_test/questions.jsonl',encoding='utf-8')];PG={json.loads(l)['id']:json.loads(l) for l in open('experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl',encoding='utf-8')}
print('public tương tự',sum('%' in r['question'] and PG[r['id']]['type']!='percent' for r in PQ))
print('--- price_effect')
for i,code,want in [('c2ce1b',"price_effect('Nước suối Aquafina 500ml','2025-05-07',days=14)",3.25),('89bd9d',"price_effect('Nước suối Lavie 1.5L','2026-01-27',days=14)",52.94),('cd78ec',"price_effect('Efferalgan 500mg viên sủi hộp 4 vỉ x 4 viên','2025-11-22',days=7)",-32.53)]:
    k=next(x for x in TQ if x[2:8]==i);q=TQ[k];s=shop(q);print(q['question'][:150],'|',eval(code,{'price_effect':s.price_effect}),want)
    name=re.search(r"'(.*?)'",code).group(1);l=s.lines[s.lines.item_name.astype(str)==name]
    d=re.search(r"'(\d{4}-\d\d-\d\d)'",code).group(1);days=int(re.search(r'days=(\d+)',code).group(1));D=pd.Timestamp(d)
    x=l.assign(day=pd.to_datetime(l.order_date).dt.normalize());x=x[x.is_revenue]
    a=x[(x.day>=D)&(x.day<D+pd.Timedelta(days=days))];b=x[(x.day<D)&(x.day>=D-pd.Timedelta(days=days))]
    print('  base',a.base_quantity.sum(),b.base_quantity.sum(),'qty',a.quantity.sum(),b.quantity.sum(),'units',a.unit.value_counts().to_dict(),b.unit.value_counts().to_dict(),'other names',[n for n in s.lines.item_name.dropna().unique() if name.split()[2 if 'suối' in name else 0] in n][:6])
print('--- cancel')
for i,want in (('008f69',1.21),('a954a4',1.96)):
    k=next(x for x in TQ if x[2:8]==i);q=TQ[k];s=shop(q);m=re.search(r'(\d+)[/ ].*?(\d{4})',q['question']);p=s.clock.month(int(re.search(r'thang (\d+)|Tháng (\d+)',q['question']).group(1) or re.search(r'Tháng (\d+)',q['question']).group(1)),int(re.search(r'(\d{4})',q['question']).group(1)))
    o=s.orders;d=pd.to_datetime(o.order_date).dt.normalize();o=o[(d>=pd.Timestamp(p.start))&(d<=pd.Timestamp(p.end))]
    print(q['question'][:50],s.cancel_rate(p),want,o.status_norm.value_counts().to_dict(),len(o))
