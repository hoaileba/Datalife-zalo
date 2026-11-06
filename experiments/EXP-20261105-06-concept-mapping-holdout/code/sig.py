import glob,os,re,json,collections,warnings;warnings.filterwarnings('ignore')
import pandas as pd
SIG={'lô/hạn':r'lot_id|expiry_date','giao đợt':r'Lượt giao|Luot giao','hạn nợ':r'due_date','hoạt chất':r'active_ingredient|is_prescription','IMEI':r'IMEI','sổ góp':r'Số kỳ|So ky','bảo hành':r'Ngày nhận|Lỗi','sửa xe':r'^Xe$|Làm gì','size/hãng':r'Số / Size|Hãng','phí trên dòng':r'x','thu máy':r'Thu máy cũ|Giá thu|Trừ vào','đăng ký':r'Ngày đăng ký'}
rows={}
for r in sorted(glob.glob('artifacts/norm/public_test/*')+glob.glob('artifacts/norm/train/*')):
    s=os.path.basename(r);cs=set()
    for p in glob.glob(r+'/*.csv'):
        if 'dropped' in p:continue
        cs|=set(pd.read_csv(p,dtype=str,nrows=1).columns)
    rows[s]=[k for k,v in SIG.items() if k!='phí trên dòng' and any(re.search(v,c) for c in cs)]
    rd=open(('public_test/data/' if s.startswith('dev') else 'train/data/')+s+'/README.md',encoding='utf-8').read().lower()
    print(s,rows[s])
Q=[json.loads(l) for l in open('train/questions.jsonl')] if os.path.exists('train/questions.jsonl') else []
print(len(Q));G={json.loads(l)['id']:json.loads(l) for l in open('train/answers.jsonl')}
D={'phone':r'máy cũ|bảo hành|góp|dòng máy|phụ kiện|may cu|bao hanh','repair':r'lượt xe|thợ|phiếu sửa|hoa hồng|biển số','giao':r'đợt|chở đi|giao từ','due':r'ngày phải trả|hạn trả','lot':r'hạn dùng|\blô\b|hsd|cận date|hết hạn','baby':r'voucher|phí ship|dùng điểm|bỉm|sữa bột|size|đăng ký','stockout':r'hết hàng|đứt hàng|cháy hàng'}
for k,p in D.items():
    x=[r for r in Q if re.search(p,r['question'].lower())]
    print('==',k,len(x),collections.Counter(r['business_id'] for r in x).most_common(6))
    for r in x[:7]: print('  ',r['business_id'],r['id'][2:8],r['question'][:78],'|',str(G[r['id']].get('answer'))[:26])
