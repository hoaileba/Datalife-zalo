import json,re,sys,collections,warnings;warnings.filterwarnings('ignore')
sys.path.insert(0,'src')
import pandas as pd
from datamate.shop import Shop
S=sys.argv[1]
B=json.load(open(S+'/bucketed.json'))
def has_year(q): return bool(re.search(r'20\d\d|/\d\d\b|-\d\d\b|\bnăm\b|nam \d',q.lower()))
noyear=[r for r in B if re.search(r'(tháng|thang|th)\s*(\d{1,2}|ba|tư|năm|sáu|bảy|tám|chín|mười)\b',r['q'].lower()) and not has_year(r['q']) and re.search(r'clock\.month\(\d+, *\d{4}\)',r['first'])]
print('no-year but model wrote year',len(noyear),[r['id'][2:8] for r in noyear][:20])
pe=[r for r in B if re.search(r'lên giá|tăng giá|đổi giá|len gia|tang gia|doi gia',r['q'].lower())]
print('price change',len(pe),collections.Counter(r['status'] for r in pe))
multi=[r for r in B if r['rt']=='list' and r['at'] in('number','unanswerable') and isinstance(r['ra'],list) and all(isinstance(x,(int,float)) for x in r['ra'])]
print('multi numeric',len(multi),collections.Counter(r['at'] for r in multi))
bq=[r for r in B if re.search(r'bình quân|binh quan|bìn quân|trung bình|trung binh',r['q'].lower()) and r['first_fn']=='revenue']
print('average asked, revenue called',len(bq))
top=[r for r in B if re.search(r'nhiều đơn|nhieu don|nhiềuđơn|nhiều lần|nhiêuf lần|nhìu đơn|số đơn',r['q'].lower()) and 'ranking' in r['first'] and 'orders' not in r['first']]
print('most orders w/o metric',len(top))
grp=[r for r in B if re.search(r'nhóm ',r['q'].lower()) and 'ranking' in r['first'] and 'group=' not in r['first']]
print('group dropped from ranking',len(grp))
ship=[r for r in B if re.search(r'(tiền mặt|ví điện tử|chuyển khoản|tại quầy|zalo|điện thoại|xi ô đi|vi dien tu|tien mat|tai quay|chuyen khoan|san thuong|sàn)',r['q'].lower()) and re.search(r'dthu|doanh thu|tiền',r['q'].lower()) and 'bucket' in r and r['bucket'].startswith('K')]
print('channel/payment leftover',len(ship))
unit=[r for r in B if r['bucket'].startswith('K') and re.search(r'(mấy|bao nhiêu|nhiêu|bnhiu|may|bao nheiu) ?(ly|lon|gói|dia|đĩa|goi)\b',r['q'].lower())]
print('total units leftover',len(unit),[ (r['id'][2:8],r['ra'],r['first'][:50]) for r in unit][:10])
print('--- literal bad after revenue',sum(r['lit'] and r['first_fn']=='revenue' and r['rt'] not in('number',) for r in B))
print('--- dev_002 size M')
s=Shop('artifacts/norm/public_test/dev_002',as_of='2026-05-24',calendar='public_test/calendar.csv')
print('--- dev_008 debt in Note')
d=pd.read_csv('artifacts/norm/public_test/dev_008/sales.csv',dtype=str)
n=d[d.note.notna()][['order_id','order_date','payment_method','note','order_total','customer_code']].drop_duplicates('order_id')
print(len(n),n.note.head(5).tolist())
print(collections.Counter(re.sub(r'[\d.,]+','N',x)[:40] for x in n.note).most_common(5))
