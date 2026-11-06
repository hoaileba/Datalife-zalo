import glob,os,re,json,collections,sys,warnings;warnings.filterwarnings('ignore')
import pandas as pd
sys.path.insert(0,'src')
from datamate_agent.column_roles import HEADER_ROLES,DESCRIPTION_ROLES,readme_columns,_description_key
from datamate_agent.normalize import fold_key
rows=[];cols=collections.defaultdict(set)
for ds,base in (('public_test','public_test/data'),('train','train/data')):
    for d in sorted(glob.glob(base+'/*')):
        s=os.path.basename(d);rd=open(d+'/README.md',encoding='utf-8').read() if os.path.exists(d+'/README.md') else ''
        first=[l for l in rd.splitlines() if l.strip() and not l.startswith('#')][:1]
        files=sorted(os.path.basename(p) for p in glob.glob(d+'/*') if not p.endswith(('README.md','questions.jsonl')))
        m=json.load(open(f'artifacts/norm/{ds}/{s}/mapping.json'))
        allc=[c for t in m['tables'] for c in t['columns']]
        rows.append((s,first[0][:95] if first else '',len(files),len(allc)))
        sec=readme_columns(rd)
        for c in allc: cols[fold_key(c)].add(s)
for r in rows: print(r)
one=[c for c,v in cols.items() if len(v)==1]
print('distinct headers',len(cols),'only in one shop',len(one))
# roles: description vs header, leave-one-out
tot=collections.Counter()
for ds,base in (('public_test','public_test/data'),('train','train/data')):
    for d in sorted(glob.glob(base+'/*')):
        s=os.path.basename(d);rd=open(d+'/README.md',encoding='utf-8').read();sec=readme_columns(rd);m=json.load(open(f'artifacts/norm/{ds}/{s}/mapping.json'))
        for t in m['tables']:
            folded={fold_key(c) for c in t['columns']};section=max(sec.values(),key=lambda k:len(folded&set(k)),default={})
            for r in t['roles']:
                k=fold_key(r['column']);via='desc' if DESCRIPTION_ROLES.get(section.get(k,'')) else 'header' if HEADER_ROLES.get(k) else 'other'
                only=via=='header' and cols[k]=={s}
                tot[via]+=1;tot['header_only_this_shop']+=only
print(tot)
