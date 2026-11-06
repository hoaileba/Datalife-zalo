import json,re,sys,glob,os,warnings,collections;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
import pandas as pd
from datamate.shop import Shop,_folded
from datamate.norm import parse_datetime
from datamate_agent.intents import period_of
from datamate_agent.question_norm import normalize
from datamate_agent.column_roles import readme_columns
from datamate_agent.normalize import fold_key
def base(s): return ('public_test' if s.startswith('dev') else 'train')
def tabledesc(s):
    rd=open(f"{base(s)}/data/{s}/README.md",encoding='utf-8').read();sec=readme_columns(rd);out={}
    m=json.load(open(f"artifacts/norm/{base(s)}/{s}/mapping.json"))
    for t in m['tables']:
        f={fold_key(c) for c in t['columns']};best=max(sec.values(),key=lambda k:len(f&set(k)),default={})
        roles={fold_key(r['column']):r['role'] for r in t['roles']}
        out[t['name']]={c:(best.get(fold_key(c),''),roles.get(fold_key(c))) for c in t['columns']}
    return out
print('=== mô tả cột theo khái niệm')
K={'đợt giao':r'dot giao','ngày giao':r'ngay giao','số lô':r'^so lo','hạn dùng':r'han su dung','nhập lô':r'so luong nhap','bán lô':r'ban lay tu lo','thu máy':r'thu may|gia thu','số kỳ':r'so ky|ky gop','góp':r'gop','xe':r'dong xe|bien so','việc':r'viec','size':r'size','đăng ký':r'dang ky','hạn nợ':r'han thanh toan|phai tra'}
shops=[os.path.basename(p) for p in sorted(glob.glob('artifacts/norm/public_test/*')+glob.glob('artifacts/norm/train/*'))]
D={s:tabledesc(s) for s in shops}
for k,p in K.items():
    c=collections.Counter();ss=set()
    for s,t in D.items():
        for n,cols in t.items():
            for col,(desc,role) in cols.items():
                if re.search(p,desc): c[(col,desc[:44])]+=1;ss.add(s)
    print(k,len(ss),'shops',sorted(ss)[:14]);print('   ',len(c),'tên cột khác nhau',c.most_common(5))
print('=== chạy theo mô tả, so với gold train')
Q={json.loads(l)['id']:json.loads(l) for l in open('train/questions.jsonl')};G={json.loads(l)['id']:json.loads(l) for l in open('train/answers.jsonl')}
ok=tot=0
def find(s,pat):
    for n,cols in D[s].items():
        for col,(desc,role) in cols.items():
            if re.search(pat,desc): return n,col
    return None
for i,q in Q.items():
    s=q['business_id']
    if not(re.search(r'đợt',q['question'].lower()) and s in('biz_117','biz_118')):continue
    sh=Shop(f"artifacts/norm/train/{s}",as_of=q['as_of_date'],calendar='train/calendar.csv')
    a,b=find(s,'dot giao'),find(s,'ngay giao');pc=period_of(normalize(q['question']));c=eval(pc,{'clock':sh.clock}) if pc else sh.clock.this_month()
    f=sh.tables[a[0]];day=pd.to_datetime(f[b[1]].map(parse_datetime),errors='coerce').dt.normalize();x=f[(day>=pd.Timestamp(c.start))&(day<=pd.Timestamp(c.end))]
    got=x[['order_id',a[1]]].drop_duplicates().shape[0];good=got==G[i]['answer'];ok+=good;tot+=1
    print(('OK ' if good else 'NO '),s,q['question'][:58],'|',got,G[i]['answer'],a[1],b[1])
print('giao',ok,'/',tot)
