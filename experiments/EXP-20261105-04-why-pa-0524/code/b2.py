import json,re,collections,sys,warnings;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
S=sys.argv[1]
from datamate_agent.fewshot import load_library,mask_question,entities_of
from datamate.shop import Shop
R=json.load(open(S+'/rows3.json'))
FN=re.compile(r'\b(revenue|order_count|quantity|average_order|cancel_rate|cancelled_orders|ranking|sold_orders|customer_count|item_count|sale_price|price_effect|debt_added|debt_repaid|debt_at|debt_aged|debtors|debtor_count|purchase_cost|avg_purchase_price|top_supplier|stock_big|stock_value|stock|purchase_minus_sold|purchase_quantity|gross_profit|net_profit|expenses|unsold_count|due_orders|best_month|repeat_vehicles|pct_change|increasing)\(')
fn=lambda c:(FN.search(c or '') or [None,None])[1]
O={json.loads(l)['id']:json.loads(l) for l in open('experiments/EXP-20261105-02-fix-norm-helper-remind/out/oracle_public.jsonl')}
lib=load_library()
ents={}
hit1=hit4=tot=0;follow=collections.Counter()
for r in R:
    r['ff'],r['tf'],r['of']=fn(r['first']),fn(r['top']),fn(O[r['id']].get('code',''))
    r['follow']=r['ff']==r['tf']
    follow[(r['st'],r['follow'])]+=1
    if r['oracle_ok']:
        if r['shop'] not in ents: ents[r['shop']]=entities_of(Shop(f"artifacts/norm/public_test/{r['shop']}",as_of=r['as_of'],calendar='public_test/calendar.csv'))
        near=lib.nearest(mask_question(r['q'],ents[r['shop']]))
        tot+=1; hit1+=near[0].intent==r['intent']; hit4+=any(e.intent==r['intent'] for e in near); r['top_right']=near[0].intent==r['intent']
print('follow top1 fn',follow);
print('retrieval on oracle-solvable',tot,'top1 intent right',hit1,round(hit1/tot,3),'top4',hit4,round(hit4/tot,3))
okk=[r for r in R if r['oracle_ok']]
for lab,f in (('top1 right',lambda r:r['top_right']),('top1 wrong',lambda r:not r['top_right'])):
    x=[r for r in okk if f(r)];print(lab,len(x),'model ok',sum(r['st']=='ok' for r in x),round(sum(r['st']=='ok' for r in x)/max(1,len(x)),3))
def has(r,p):return bool(re.search(p,r['q'].lower()))
RULES=[
('U Trả lời câu đáng lẽ unanswerable',lambda r:r['rt']=='unanswerable'),
('T Thiếu trả góp, sổ nợ dev_014',lambda r:has(r,r'góp|tra gop|tien gop')or(r['shop']=='dev_014' and has(r,r'nợ|no\b|công nợ'))),
('T Thiếu bảo hành',lambda r:has(r,r'bảo hành|bao hanh')),
('T Thiếu thu máy cũ, khách phải trả',lambda r:has(r,r'máy cũ|may cu|phải trả|phai tra|phãi trả|điện thoại cũ') and r['shop'] in('dev_011','dev_014')),
('T Thiếu dòng máy, máy không phụ kiện',lambda r:r['shop'] in('dev_011','dev_014') and has(r,r'máy|may\b|chiếc|điện thoại|dien thoai|xiaomi|samsung|iphone')),
('T Thiếu xe, hoa hồng, phiếu dev_012',lambda r:r['shop']=='dev_012'),
('T Thiếu đợt giao, ngày phải trả dev_004',lambda r:r['shop']=='dev_004' and has(r,r'đợt|dot\b|chở|giao|ngày phải trả')),
('T Thiếu lô, hạn dùng, hết hàng dev_006',lambda r:r['shop']=='dev_006' and has(r,r'\blô\b|\blo\b|hsd|hạn|hết hàng|het hang|đứt hàng|chay hang|cận date')),
('T Thiếu phí ship, voucher, điểm',lambda r:has(r,r'phí ship|phi ship|voucher|vâu chơ|dung diem|dùng điểm')),
('T Thiếu hãng, số, size bỉm và sữa',lambda r:r['shop']=='dev_013' and has(r,r'bỉm|bim\b|sữa bột|sua bot')),
('M Đổi giá: sai ngày hoặc số',lambda r:has(r,r'lên giá|tăng giá|đổi giá|len gia|tang gia|doi gia')),
('M Hỏi nhiều số, trả một số',lambda r:r['rt']=='list' and all(isinstance(x,(int,float)) for x in r['ra'])),
('M Lãi gộp, lãi ròng gọi sai hàm',lambda r:has(r,r'l[aã]i|lợi nhuận|loi that')),
('M Trung bình mỗi đơn gọi revenue',lambda r:has(r,r'bình quân|binh quan|bìn quân|trung b[iì]nh') ),
('M Đếm đơn vị (ly, lon, đĩa) gọi sai',lambda r:has(r,r'\b(ly|lon|đĩa|dia|gói|goi)\b') and r['rt']=='number'),
('M Thiếu lọc nhóm hàng khi xếp hạng',lambda r:has(r,r'nhóm') and 'group=' not in r['code']),
('M Nhiều đơn nhất thiếu metric orders',lambda r:has(r,r'nhi[eêề]u.{0,3}đ?d?[oơ]n|nhiều lần') and 'orders' not in r['code']),
('M Tháng không ghi năm, sai năm',lambda r:not re.search(r'20\d\d|/\d\d|\d-\d\d|năm',r['q'].lower()) and re.search(r'clock\.month\(\d+, *\d{4}\)',r['code'])),
('M Từ cần tra rulebook',lambda r:has(r,r'trung thành|sộp|đắt khách|ưa chuộng|chăm chỉ|bán giỏi|đổi ý|trung thực|nhà cung cấp chính|uy tín')),
('M Số khách nợ, giá trị tồn gọi sai',lambda r:has(r,r'số khách|bao nhiêu khách|mấy khách')or has(r,r'giá vốn|gia von')),
]
c=collections.defaultdict(list)
for r in R:
    if r['st']=='ok':continue
    b=next((n for n,f in RULES if f(r)),'M Còn lại: sai hàm hoặc tham số')
    r['bucket']=b;c[b].append(r)
gl=collections.Counter()
for b,x in sorted(c.items(),key=lambda p:-len(p[1])):
    w=sum(r['st']=='wrong' for r in x);bl=len(x)-w;gain=(2*w+bl)/1000
    gl[b[0]]+=gain;print(f"{len(x):3d} w{w:3d} b{bl:2d} +{gain:.3f} {b:42s} t2={sum(r['turns']==2 for r in x):3d} {collections.Counter(r['shop'][-3:] for r in x).most_common(3)}")
print({k:round(v,3) for k,v in gl.items()},sum(len(v) for v in c.values()))
print('--- rest')
for r in c['M Còn lại: sai hàm hoặc tham số']: print(r['id'][2:8],r['shop'][-3:],r['q'][:58],'|',r['first'][:62].replace('\n',' '))
print('--- typeok: helper-backed oracle right but model wrong',sum(r['oracle_ok'] for x in c.values() for r in x))
json.dump([r for r in R if r['st']!='ok'],open(S+'/bucket3.json','w'),ensure_ascii=False,default=str)
