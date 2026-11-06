import json,sys,collections,warnings,re;warnings.filterwarnings('ignore')
from collections import Counter
sys.path.insert(0,'src')
from datamate_agent import fewshot as F
from datamate_agent.question_norm import normalize
from datamate.shop import Shop
lib=F.load_library();E=lib.examples
print('lib',len(E),{k:sum(e.intent==k for e in E) for k in('gross_profit','net_profit','average_order','debtor_count','stock_value','revenue_months','customers_share')})
O=[json.loads(l) for l in open('experiments/EXP-20261105-02-fix-norm-helper-remind/out/oracle_public.jsonl')]
ents={}
def mask(r):
    s=r['business_id']
    if s not in ents: ents[s]=F.entities_of(Shop(f'artifacts/norm/public_test/{s}',as_of=r['as_of_date'],calendar='public_test/calendar.csv'))
    return F.mask_question(r['question'],ents[s])
P=[(mask(r),r['intent']) for r in O if r['ok']]
orig=F._terms
def ev(name,fn):
    F._terms=fn;L=F.Library(E);t1=t4=0;fails=Counter()
    for q,i in P:
        n=L.nearest(q);t1+=n[0].intent==i;t4+=any(e.intent==i for e in n)
        if n[0].intent!=i:fails[(i,n[0].intent)]+=1
    print(f'{name:26s} top1 {t1}/{len(P)} {t1/len(P):.3f} top4 {t4/len(P):.3f}',fails.most_common(5) if name in('hiện tại','từ 1-2 có chuẩn hoá') else '')
    F._terms=orig
words=lambda t:re.findall(r'\w+',t.lower())
def wb(t):
    w=words(t);return Counter(w+[a+' '+b for a,b in zip(w,w[1:])])
def ch(a,b):
    def f(t):
        s=' '+' '.join(words(t))+' ';return Counter(s[i:i+n] for n in range(a,b+1) for i in range(len(s)-n+1))
    return f
ev('hiện tại',orig)
ev('từ 1-2',wb)
ev('từ 1-2 có chuẩn hoá',lambda t:wb(normalize(t)))
ev('char 3-5',ch(3,5))
ev('char 3-5 có chuẩn hoá',lambda t:ch(3,5)(normalize(t)))
