import json,re,glob,sys,collections,os
sys.path.insert(0,'src')
from datamate_agent.score import is_correct
N='experiments/EXP-20261104-05-public-1000-v7'
R=glob.glob(N+'/run/*/answers.jsonl')[0]; D=os.path.dirname(R)
load=lambda p:{json.loads(l)['id']:json.loads(l) for l in open(p,encoding='utf-8') if l.strip()}
A,Q,G=load(R),load(N+'/inputs/questions.jsonl'),load(N+'/inputs/claude_reference.jsonl')
rows=[]
for i,q in Q.items():
    a=A.get(i,{}); g=G[i]
    t=open(f'{D}/{i}.log',encoding='utf-8').read() if os.path.exists(f'{D}/{i}.log') else ''
    body=t.split('Turn 0',1)[-1]
    codes=re.findall(r'\[CALL\] (run|final)\n\[CODE\]\n(.*?)\n\[OUTPUT\]\n(.*?)(?=\n\nTurn|\n\n--------|\nTurn |\Z)',body,flags=re.S)
    turns=len(re.findall(r'^Turn \d+',t,flags=re.M))
    helpers=re.findall(r'\b([a-z_]+)\(',codes[-1][1]) if codes else []
    status='blank' if a.get('type') in (None,'abstain') else 'ok' if is_correct(a,g) else 'wrong'
    errs=[c[2][:120] for c in codes if re.match(r'\s*(Traceback|\w*Error|ValueError|KeyError)',c[2]) or 'Error' in c[2][:60]]
    rows.append(dict(id=i,shop=q['business_id'],q=q['question'],as_of=q['as_of_date'],status=status,at=a.get('type'),aa=a.get('answer'),rt=g['type'],ra=g.get('answer'),reason=g.get('reason'),turns=turns,code=codes[-1][1] if codes else '',ncode=len(codes),helpers=helpers,errs=errs))
json.dump(rows,open(sys.argv[1],'w',encoding='utf-8'),ensure_ascii=False,default=str)
c=collections.Counter(r['status'] for r in rows);print(c)
bad=[r for r in rows if r['status']!='ok']
print('no code',sum(not r['ncode'] for r in bad),'err seen',sum(bool(r['errs']) for r in bad))
