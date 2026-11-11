"""Normalizing noisy Vietnamese questions for matching: accents off, telex typos undone, abbreviations expanded."""
from __future__ import annotations

import re
import unicodedata

ABBREV = [
    (r'\bdthu\b', 'doanh thu'), (r'\brevenue\b', 'doanh thu'), (r'\bbnhiu\b', 'bao nhieu'), (r'\bbn\b', 'bao nhieu'),
    (r'\bbao nhiu\b', 'bao nhieu'), (r'\bnhiu\b', 'nhieu'), (r'\bdc\b', 'duoc'), (r'\bhnay\b', 'hom nay'),
    (r'\bhqua\b', 'hom qua'), (r'\bbua qua\b', 'hom qua'), (r'\bbua nay\b', 'hom nay'), (r'\btrc\b', 'truoc'),
    (r'\bvs\b', 'voi'), (r'\bth\b', 'thang'), (r'\bsp\b', 'san pham'), (r'\bko\b', 'khong'),
    (r'\bbill\b', 'don'), (r'\border\b', 'don'), (r'\btotal\b', 'tong cong'), (r'\bbest seller\b', 'ban chay nhat'),
    (r'\btm\b', 'tien mat'), (r'\bck\b', 'chuyen khoan'), (r'\bnhieu\b', 'nhieu'), (r'\bnhieeu\b', 'nhieu'),
    (r'\bvaayj\b', 'vay'), (r'\bla j\b', 'la gi'),
]

TELEX_TAIL = re.compile(r'\b([a-z]*[aeiouy][a-z]*?)([fsrxj])\b')


def fold(s: str) -> str:
    s = unicodedata.normalize('NFD', unicodedata.normalize('NFC', s).lower()).replace('đ', 'd')
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def detelex_word(w: str) -> str:
    """Undo one stray telex key: 'hangf' -> 'hang', 'dduwowcj' -> 'duoc', 'thangs' -> 'thang'."""
    if not w.isalpha():
        return w
    w2 = w
    for a, b in (('dd', 'd'), ('aa', 'a'), ('ee', 'e'), ('oo', 'o'), ('aw', 'a'), ('ow', 'o'), ('uw', 'u'),
                 ('w', '')):
        w2 = w2.replace(a, b)
    if len(w2) > 2 and w2[-1] in 'fsrxj' and w2[-2] in 'aeiouyhngtcpm' and w2 not in KEEP_FINAL:
        w2 = w2[:-1]
    return w2


KEEP_FINAL = {'tes', 'chuyens', 'ms', 'kgs', 'lens'}


def norm_question(q: str) -> str:
    s = fold(q)
    s = s.replace('≥', ' tu ').replace('–', '-').replace('—', '-')
    toks = re.findall(r'[a-z]+|\d+(?:[.,]\d+)*|[^\sa-z\d]', s)
    known = KNOWN
    out = []
    for t in toks:
        if t.isalpha() and t not in known:
            d = detelex_word(t)
            t = d if d in known else t
        out.append(t)
    s = ' '.join(out)
    s = re.sub(r'(\d) / (\d)', r'\1/\2', s)
    s = re.sub(r'(\d) / (\d)', r'\1/\2', s)
    for pat, rep in ABBREV:
        s = re.sub(pat, rep, s)
    return re.sub(r'\s+', ' ', s).strip()


# Words of the question vocabulary (folded) used to accept a telex correction.
KNOWN = set('''
doanh thu thang nam ngay tuan quy hom nay qua truoc roi nay bao nhieu may tong cong cua hang ban duoc tien don
khach mat hang san pham nhom nao nhat cao thap chay hot top liet ke la gi ai so voi thay doi tang giam phan tram
ti le ty huy tra lai gop von nhap kho ton cuoi het han lo thuoc ke hoat chat chat gia binh quan trung mot moi
dau gan tro len it toi thieu bang chiem trong tinh den gio ca sang chieu nhan vien chi tieu nhieu hon kem
cung ky lien giao dot xe cho giup xem hoi biet minh toi check coi gium giu vay nhi nha ha ta do a e oi
lan luot theo thu tu ghi hai hoac va hay khong co phai dang con no thu hoi chiu them bot tuoi nguyen le chan
cai chai lon hop goi vien vi ly bao kg cay bo thung binh tuyp m3 met cuon dia phan to chiec tam vien
tet dip mua nam ngoai nhung cac luong qua tren duoi dat dong mang ve gia tri hang hoa cong no ngay
size phong lanh dien thoai quay zalo chuyen khoan mat vi cod tung hinh thuc ban le si than thiet
'''.split())
