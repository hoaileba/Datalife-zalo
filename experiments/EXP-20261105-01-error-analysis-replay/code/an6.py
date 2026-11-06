import json,re,collections,sys
S=sys.argv[1]
R=json.load(open(S+'/rows2.json'));SAME=set(json.load(open(S+'/same_entity.json')))
Dom=[
 ('D-trả góp',r'góp|tra gop|\bgop\b'),
 ('D-bảo hành',r'bảo hành|bao hanh'),
 ('D-thu máy cũ / khách phải trả',r'thu (lại )?máy cũ|thu may cu|tiền thu máy|tien thu may|phải trả|phai tra|phãi trả|tru bot|trừ bớt|trừ tiền bớt'),
 ('D-hoa hồng thợ',r'hoa hồng|huê hồng|hoa hong'),
 ('D-lô, hạn dùng, hết hàng',r'\blô\b|hsd|hạn dùng|hết hạn|cận date|hết hàng|đứt hàng|het hang|chay hang|cháy hàng'),
 ('D-đợt giao',r'đợt|\bdot\b|chở|giao tổng|xe đã giao'),
 ('D-ngày phải trả',r'ngày phải trả'),
 ('D-phí ship, voucher, điểm',r'phí ship|phi ship|voucher|vâu chơ|dung diem|dùng điểm'),
 ('D-xe, phiếu, dịch vụ',r'\bxe\b|lượt xe|nượt xe|luot xe|phiếu'),
 ('D-bỉm, sữa theo hãng, size',r'bỉm|bim|sữa bột|sua bot'),
 ('D-máy theo dòng, không phụ kiện',r'phụ kiện|dien thoai|điện thoại|dòng máy|dong may|\bmáy\b|may samsung|chiếc xiaomi|chiec'),
]
def bucket(r):
    q=r['q'].lower()
    if r['id'] in SAME: return 'X-cùng đối tượng, chấm sai'
    if r['rt']=='unanswerable': return 'U-đáng lẽ unanswerable'
    for n,p in Dom:
        if re.search(p,q): return n
    if r['at']=='unanswerable' and r['oracle_ok']: return 'M-unanswerable dù helper giải được'
    if r['first_fn']=='revenue' and r['top_fn']!='revenue': return 'M-bỏ ví dụ, gọi revenue'
    if r['oracle_ok']: return 'M-helper đúng, model gọi sai tham số'
    return 'K-còn lại'
c=collections.Counter();sc=collections.defaultdict(list)
for r in R:
    if r['status']=='ok':continue
    b=bucket(r);r['bucket']=b;c[b]+=1;sc[b].append(r)
tot=sum(c.values())
for b,n in c.most_common():
    print(n,b,'wrong',sum(x['status']=='wrong' for x in sc[b]),'blank',sum(x['status']=='blank' for x in sc[b]),collections.Counter(x['shop'][-3:] for x in sc[b]).most_common(4))
print(tot)
json.dump([r for r in R if r['status']!='ok'],open(S+'/bucketed.json','w'),ensure_ascii=False,default=str)
for r in sc['K-còn lại']:
    print(r['id'][2:8],r['shop'][-3:],r['intent'][:14],'|',r['q'][:85],'| ref',str(r['ra'])[:28],'| got',str(r['aa'])[:28],'|',r['first'][:75].replace('\n',' '))
