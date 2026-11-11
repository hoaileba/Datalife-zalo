"""Coarse intent bucket of every train question (keyword rules; for capping in gen.mix only, not for answers).

python scripts/train_intents.py > data_gen/train_intents.jsonl   (run from the repo root; train data only)
"""
import json,collections,re,unicodedata,sys
from pathlib import Path
TRAIN = Path(__file__).resolve().parents[1] / 'data' / 'train'      # any working directory (gen.package imports this)
Q=[json.loads(l) for l in open(TRAIN / 'questions.jsonl', encoding='utf-8')]
A={json.loads(l)['id']:json.loads(l) for l in open(TRAIN / 'answers.jsonl', encoding='utf-8')}
def fold(s):
    s=unicodedata.normalize('NFD',s.lower()).replace('đ','d')
    s=''.join(c for c in s if unicodedata.category(c)!='Mn')
    # undo telex typos roughly
    s=re.sub(r'([a-z])[fsrxj](?=\s|$)',r'\1',s)
    s=re.sub(r'dd','d',s); s=re.sub(r'aw','a',s); s=re.sub(r'ow','o',s); s=re.sub(r'uw','u',s); s=re.sub(r'ee','e',s); s=re.sub(r'oo','o',s); s=re.sub(r'aa','a',s)
    return s
R=[
('unans_like', None),
('price_effect', r'tang gia|len gia|doi gia|giam gia tu|ha gia'),
('expiry', r'het han|han dung|han su dung|\blo\b'),
('debt_age', r'tuoi no|no qua|no lau'),
('debt_new', r'no them|mua chiu.*(them|moi)|ghi no them'),
('debt_paid', r'tra no|thu no|tra bot no|tra bot'),
('debt', r'\bno\b|cong no'),
('stock_value', r'gia tri.*(ton|kho)|tien hang ton'),
('out_of_stock', r'het hang|het sach'),
('stock', r'\bton\b|trong kho|con lai|con bao'),
('avg_cost', r'gia nhap binh quan|binh quan.*nhap'),
('purchase', r'nhap|phieu nhap|nha cung cap|ncc'),
('net_profit', r'lai rong|loi rong|chi phi'),
('gross_profit', r'lai|loi|gia von'),
('unsold', r'\be\b|khong ban.*(duoc|ra)|ko ai mua|khong ai mua'),
('price_on_day', r'gia bao nhieu|don gia|gia ban|gia mot'),
('cancel_rate', r'(ti|ty) le.*huy|% don.*huy|phan tram don.*huy|huy.*(%|phan tram)'),
('cancel_count', r'huy'),
('return', r'tra hang|tra lai'),
('delivery', r'dot giao|dot hang|giao hang|giao'),
('shift', r'ca sang|ca chieu'),
('staff', r'nhan vien|\bnv'),
('rx', r'ke don|hoat chat'),
('size', r'size|\(m\)|\(l\)'),
('payment', r'tien mat|chuyen khoan|cod|thanh toan|the\b|vi dien tu|momo'),
('cust_group', r'nhom khach|khach (si|le|vip|quen|than thiet)'),
('customer', r'khach'),
('basket', r'don khac nhau|xuat hien|co mat o'),
('best_day', r'ngay nao'),
('best_month', r'thang nao'),
('trend', r'lien tuc|tang deu'),
('share', r'ti trong|ty trong|chiem|dong gop|phan tram|%|phan cua'),
('top_items', r'ban chay|ban nhieu|hot|top|lien ke'),
('qty_unit', r'bao nhieu (kg|cai|chai|lon|bao|vien|hop|ly|cay|bo|m3|binh|thung|goi)|may (kg|cai|chai|lon|bao|vien|hop|ly|cay|bo|m3|binh|thung|goi)|so (kg|cai|chai|lon|bao|vien|hop|ly|cay|bo|m3|binh|thung|goi)'),
('avg_order', r'trung binh|binh quan'),
('days_over', r'may ngay|so ngay'),
('orders_over', r'don.*(dat|tu|tren).*(tro len|d\b|dong)'),
('order_count', r'don'),
('revenue', r'doanh thu|dthu|tien|ban duoc|ban dc|thu ve'),
]
def intent(q, a):
    if a['type'] == 'unanswerable':
        return 'UNANSWERABLE'
    f = fold(q)
    for name, pat in R[1:]:
        if re.search(pat, f):
            return name
    return 'OTHER'


if __name__ == '__main__':
    for q in Q:
        print(json.dumps({'id': q['id'], 'intent': 'train:' + intent(q['question'], A[q['id']]), 'industry': None,
                          'family': None}))
