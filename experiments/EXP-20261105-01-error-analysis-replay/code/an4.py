import json,sys,glob,re,unicodedata,collections
import pandas as pd,warnings;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
from datamate.shop import Shop,HELPERS,pct_change,increasing
S=sys.argv[1]
R=json.load(open(S+'/rows2.json'))
def fold(x):
    t=unicodedata.normalize('NFD',str(x)).casefold().replace('đ','d')
    t=''.join(c for c in t if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^0-9a-z]+',' ',t).split())
cache={}
def rows_of(shop):
    if shop not in cache:
        out=[]
        for p in glob.glob(f'artifacts/norm/public_test/{shop}/*.csv'):
            if p.endswith('.dropped.csv'):continue
            d=pd.read_csv(p,dtype=str,nrows=200000).fillna('')
            cols=[c for c in d.columns if re.search(r'customer|khach|ten|name|code|ma|supplier|ncc|staff|nv|nhan',c,flags=re.I) and not re.search(r'item|source',c,flags=re.I)]
            if not cols: continue
            out.extend(set(' | '.join(fold(v) for v in t) for t in d[cols].drop_duplicates().itertuples(index=False)))
        cache[shop]=out
    return cache[shop]
def same(shop,a,b):
    a,b=fold(a),fold(b)
    if a==b:return True
    if not a or not b:return False
    return any(a in r and b in r for r in rows_of(shop))
res=[]
for r in R:
    if r['status']!='wrong' or r['at']!=r['rt']:continue
    if r['rt']=='string': ok=same(r['shop'],r['aa'],r['ra'])
    elif r['rt']=='list' and isinstance(r['aa'],list) and isinstance(r['ra'],list) and len(r['aa'])==len(r['ra']) and all(isinstance(x,str) for x in r['ra']):
        ok=all(same(r['shop'],a,b) for a,b in zip(r['aa'],r['ra']))
    elif r['rt']=='table' and isinstance(r['aa'],dict) and isinstance(r['ra'],dict):
        A,B=r['aa'].get('rows',[]),r['ra'].get('rows',[])
        ok=len(A)==len(B) and all(same(r['shop'],a[0],b[0]) and a[1:]==b[1:] for a,b in zip(A,B))
        print('TABLE',r['id'][2:8],r['shop'],ok,json.dumps(A[:2],ensure_ascii=False),json.dumps(B[:2],ensure_ascii=False))
    else: continue
    if ok: res.append(r['id']);print('SAME',r['id'][2:8],r['shop'],r['rt'],str(r['aa'])[:50],'==',str(r['ra'])[:50])
json.dump(res,open(S+'/same_entity.json','w'))
print('same entity',len(res),collections.Counter(next(x['shop'] for x in R if x['id']==i) for i in res))
