import json,re,glob,os,collections
import pandas as pd
C='artifacts/normalize-train/clean/'
q={j['id']:j for j in map(json.loads,open('train/split/train_questions.jsonl'))}
a={j['id']:j for j in map(json.loads,open('train/split/train_answers.jsonl'))}
PAT=re.compile(r'^(?:.{0,40}?)(?:doanh thu|dthu|doanh số)\s*(?:của\s*)?(?:cửa hàng\s*|quán\s*|tiệm\s*)?(?:trong\s*)?(?:tháng|th|t)\s*(\d{1,2})\s*[/ ]\s*(?:năm\s*)?(\d{4})(?:\s*(?:là|được|đc|bao|bn|bnhiu|mấy|\?|$).{0,25})?$',re.I)
cases=collections.defaultdict(list)
for i,x in q.items():
    if a[i]['type']!='number': continue
    m=PAT.match(x['question'].strip())
    if m: cases[x['business_id']].append((i,int(m.group(1)),int(m.group(2)),x['question'],a[i]['answer']))
print('cases',sum(map(len,cases.values())),'shops',len(cases))
def sales(shop):
    best=None
    for f in glob.glob(C+shop+'/*.csv'):
        if f.endswith('.dropped.csv'): continue
        h=open(f,encoding='utf-8').readline().strip().split(',')
        if 'line_amount' in h and 'year' in h and 'is_revenue' in h:
            n=os.path.getsize(f)
            if best is None or n>best[0]: best=(n,f)
    return None if best is None else pd.read_csv(best[1],low_memory=False)
tot=collections.Counter(); bad=[]
names={}
for shop in sorted(os.listdir(C)):
    if shop not in cases:
        f=sales(shop); tot['shop_no_case']+=1; continue
    f=sales(shop)
    if f is None:
        tot['no_table']+=len(cases[shop]); bad.append((shop,'NO TABLE',[c for c in os.listdir(C+shop) if c.startswith('sales') and 'dropped' not in c][:3])); continue
    ok=0
    for i,m,y,t,want in cases[shop]:
        got=int(f[f.is_revenue.astype(str).eq('True')&(f.year==y)&(f.month==m)].line_amount.sum())
        if got==want: ok+=1
        else: bad.append((shop,t[:48],got,want,round(got/want,3) if want else None))
    tot['ok']+=ok; tot['n']+=len(cases[shop])
print(dict(tot))
for b in bad[:45]: print(b)
