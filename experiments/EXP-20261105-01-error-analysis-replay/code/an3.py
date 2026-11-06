import json,re,glob,os,collections,sys
S=sys.argv[1]
N='experiments/EXP-20261104-05-public-1000-v7'
D=os.path.dirname(glob.glob(N+'/run/*/answers.jsonl')[0])
rows=json.load(open(S+'/rows.json'))
O={json.loads(l)['id']:json.loads(l) for l in open(S+'/oracle_public.jsonl')}
def fn(code):
    m=re.search(r'\b(revenue|order_count|quantity|average_order|cancel_rate|cancelled_orders|ranking|sold_orders|customer_count|item_count|sale_price|price_effect|debt_added|debt_repaid|debt_at|debt_aged|debtors|debtor_count|purchase_cost|avg_purchase_price|top_supplier|stock_big|stock_value|stock|purchase_minus_sold|gross_profit|net_profit|expenses|unsold_count|due_orders|best_month|repeat_vehicles|pct_change|increasing)\(',code or '')
    return m.group(1) if m else None
out=[]
for r in rows:
    t=open(f"{D}/{r['id']}.log",encoding='utf-8').read()
    ex=re.findall(r'^  FINAL (\w+): (.*)$',t.split('--------')[0] if False else t,flags=re.M)
    ass=t.split('ASSISTANCE:',1)[1] if 'ASSISTANCE:' in t else ''
    codes=re.findall(r'\[CALL\] (run|final)\n\[CODE\]\n(.*?)\n\[OUTPUT\]\n',ass,flags=re.S)
    first=codes[0][1] if codes else ''
    lit=False
    if codes:
        lit=bool(re.fullmatch(r'\s*-?[\d.]+\s*|\s*".*"\s*|\s*\'.*\'\s*',codes[-1][1],flags=re.S))
    r.update(top1=ex[0][1] if ex else '',top1t=ex[0][0] if ex else '',first=first,first_fn=fn(first),top_fn=fn(ex[0][1]) if ex else None,lit=lit,last_call=codes[-1][0] if codes else None,tmatch=bool(ex) and ex[0][0]==r['rt'])
    # any example type/fn
    r['ex_fns']=[fn(e[1]) for e in ex]
    r['oracle_fn']=fn(O[r['id']].get('code',''))
    r['oracle_ok']=O[r['id']]['ok'];r['intent']=O[r['id']]['intent']
    out.append(r)
json.dump(out,open(S+'/rows2.json','w'),ensure_ascii=False,default=str)
for st in('ok','wrong','blank'):
    rs=[r for r in out if r['status']==st]
    print(st,len(rs),'first=top1 fn',sum(r['first_fn']==r['top_fn'] for r in rs),'first revenue',sum(r['first_fn']=='revenue' for r in rs),'literal final',sum(r['lit'] for r in rs))
w=[r for r in out if r['status']=='wrong']
print('wrong first_fn', collections.Counter(r['first_fn'] for r in w).most_common(12))
print('first revenue & top1 not revenue',sum(r['first_fn']=='revenue' and r['top_fn']!='revenue' for r in w),'ok analog',sum(r['first_fn']=='revenue' and r['top_fn']!='revenue' for r in out if r['status']=='ok'))
print('all: first_fn=revenue, top not',sum(r['first_fn']=='revenue' and r['top_fn']!='revenue' for r in out))
print('oracle ok but model wrong: first revenue',sum(r['first_fn']=='revenue' for r in w if r['oracle_ok']),'of',sum(r['oracle_ok'] for r in w))
print('correct fn in top1 (by oracle_fn) among oracle ok wrong',sum(r['top_fn']==r['oracle_fn'] for r in w if r['oracle_ok']))
# when model follows top1 vs not
for lab,f in (('follow',lambda r:r['first_fn']==r['top_fn']),('notfollow',lambda r:r['first_fn']!=r['top_fn'])):
    rs=[r for r in out if f(r)];print(lab,len(rs),'acc',round(sum(r['status']=='ok' for r in rs)/len(rs),3))
sh=collections.Counter()
for r in out:
    if r['first_fn']=='revenue' and r['top_fn']!='revenue': sh[r['shop']]+=1
print(sorted(sh.items()))
