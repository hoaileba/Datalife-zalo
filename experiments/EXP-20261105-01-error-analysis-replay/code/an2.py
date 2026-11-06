import json,sys,collections,re
S=sys.argv[1]
rows=json.load(open(S+'/rows.json'))
O={json.loads(l)['id']:json.loads(l) for l in open(S+'/oracle_public.jsonl')}
def short(v,n=70):
    s=json.dumps(v,ensure_ascii=False,default=str);return s if len(s)<=n else s[:n]+'…'
bad=[r for r in rows if r['status']!='ok']
bad.sort(key=lambda r:(r['shop'],O[r['id']]['intent']))
for r in bad:
    o=O[r['id']]
    print(f"{r['id'][2:8]} {r['shop'][-3:]} [{r['status'][0]}] {o['intent'][:18]}{'+' if o['ok'] else ''} | {r['q'][:110]}\n   ref {r['rt']}:{short(r['ra'])}{' R:'+r['reason'][:60] if r.get('reason') else ''}\n   got {r['at']}:{short(r['aa'])} t{r['turns']}\n   code {r['code'][:130]!r}" + (f"\n   orc {short(o.get('got'))}" if o['intent']!='UNMATCHED' and not o['ok'] else ''))
