import json,re,glob,sys,collections,os,unicodedata
import pandas as pd
sys.path.insert(0,'src')
from datamate_agent.score import is_correct
P='experiments/EXP-20261105-02-fix-norm-helper-remind'
S=sys.argv[1]
R=glob.glob(P+'/run/public/*/answers.jsonl')[0];D=os.path.dirname(R)
load=lambda p:{json.loads(l)['id']:json.loads(l) for l in open(p,encoding='utf-8') if l.strip()}
A=load(P+'/out/submission.jsonl');Q=load('public_test/questions.jsonl');G=load('experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl');O=load(P+'/out/oracle_public.jsonl')
Old=load(glob.glob('experiments/EXP-20261104-05-public-1000-v7/run/*/answers.jsonl')[0])
def fold(x):
    t=unicodedata.normalize('NFD',str(x)).casefold().replace('đ','d');t=''.join(c for c in t if not unicodedata.combining(c));return ' '.join(re.sub(r'[^0-9a-z]+',' ',t).split())
cache={}
def rws(shop):
    if shop not in cache:
        out=[]
        for p in glob.glob(f'artifacts/norm/public_test/{shop}/*.csv'):
            if p.endswith('.dropped.csv'):continue
            d=pd.read_csv(p,dtype=str,nrows=200000).fillna('')
            cols=[c for c in d.columns if re.search(r'customer|khach|ten|name|code|ma|supplier|ncc|staff|nv|nhan',c,flags=re.I) and not re.search(r'item|source',c,flags=re.I)]
            if cols: out.extend(set(' | '.join(fold(v) for v in t) for t in d[cols].drop_duplicates().itertuples(index=False)))
        cache[shop]=out
    return cache[shop]
def same(shop,a,b):
    a,b=fold(a),fold(b);return a==b or (bool(a) and bool(b) and any(a in r and b in r for r in rws(shop)))
def status(a,g,shop):
    if a['type']=='abstain':return 'blank'
    if is_correct(a,g):return 'ok'
    if a['type']==g['type']:
        if g['type']=='string' and same(shop,a['answer'],g['answer']):return 'ok'
        if g['type']=='list' and all(isinstance(x,str) for x in g['answer']) and isinstance(a['answer'],list) and len(a['answer'])==len(g['answer']) and all(same(shop,x,y) for x,y in zip(a['answer'],g['answer'])):return 'ok'
        if g['type']=='table' and len(a['answer']['rows'])==len(g['answer']['rows']) and all(same(shop,x[0],y[0]) and x[1:]==y[1:] for x,y in zip(a['answer']['rows'],g['answer']['rows'])):return 'ok'
    return 'wrong'
rows=[]
for i,q in Q.items():
    a,g=A[i],G[i];t=open(f'{D}/{i}.log',encoding='utf-8').read();ass=t.split('ASSISTANCE:',1)[-1]
    codes=re.findall(r'\[CALL\] (run|final)\n\[CODE\]\n(.*?)\n\[OUTPUT\]\n(.*?)(?=\n\[RESULT|\n--------|\nTurn \d)',ass,flags=re.S)
    ex=re.findall(r'^  FINAL (\w+): (.*)$',t.split('ASSISTANCE:',1)[0],flags=re.M)
    rows.append(dict(id=i,shop=q['business_id'],q=q['question'],as_of=q['as_of_date'],st=status(a,g,q['business_id']),at=a['type'],aa=a.get('answer'),rt=g['type'],ra=g.get('answer'),reason=g.get('reason'),turns=len(re.findall(r'^Turn \d+',ass,flags=re.M)),first=codes[0][1] if codes else '',code=' ;; '.join(c[1] for c in codes),out0=codes[0][2][:150] if codes else '',top=ex[0][1] if ex else '',intent=O[i]['intent'],oracle_ok=O[i]['ok'],oracle=str(O[i].get('got'))[:50],oldok=is_correct(Old[i],g) if Old[i].get('type') not in(None,'abstain') else False,noshop='shop has no' in ass,err=bool(re.search(r'ERROR',ass))))
json.dump(rows,open(S+'/rows3.json','w'),ensure_ascii=False,default=str)
c=collections.Counter(r['st'] for r in rows);print(c,'PA',(c['ok']-c['wrong'])/1000)
bad=[r for r in rows if r['st']!='ok']
print('types',collections.Counter((r['at'],r['rt']) for r in bad).most_common(14))
print('oracle ok among bad',sum(r['oracle_ok'] for r in bad),'unmatched',sum(r['intent']=='UNMATCHED' for r in bad))
print('turns',sorted(collections.Counter(r['turns'] for r in bad).items()))
print('noshop',sum(r['noshop'] for r in bad),'err',sum(r['err'] for r in bad),'first=final/no code',sum(not r['first'] for r in bad))
print('shop',sorted(collections.Counter(r['shop'][-3:] for r in bad).items()))
def short(v,n=52):
    s=json.dumps(v,ensure_ascii=False,default=str);return s if len(s)<=n else s[:n]+'…'
bad.sort(key=lambda r:(r['shop'],r['intent']))
with open(S+'/bad3.txt','w') as f:
    for r in bad:
        f.write(f"{r['id'][2:8]} {r['shop'][-3:]} {r['st'][0]} {r['intent'][:14]}{'+' if r['oracle_ok'] else ''} | {r['q'][:100]}\n  ref {r['rt']}:{short(r['ra'])} | got {r['at']}:{short(r['aa'])} t{r['turns']}\n  code {r['code'][:115]!r}\n")
