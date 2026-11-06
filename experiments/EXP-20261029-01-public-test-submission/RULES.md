# Luat ap dung cho EXP-20261029-01-public-test-submission

## Da code hoa
| Luat rulebook | File |
| --- | --- |
| §2 toan bo luat thoi gian (ngay, tuan T2, thang nay vs thang truoc cung so ngay, N ngay gan nhat, tu dau nam, thang/quy khong ghi nam, Tet am lich, ca sang/chieu) | `code/datamate/periods.py` |
| §8 + case 1-11 parse gia tri ban (dau `,` ngan nghin, hau to `d`/`k`/`tr`, serial Excel, ngay tieng Viet, so am, so dang string) | `code/datamate/norm.py` |
| §8 header khong o dong dau, o trong ke thua theo nhom dong, dong trung hoan toan | `code/datamate/io.py` |
| §9 format 8 type + lam tron tien ve dong, percent 2 chu so | `code/datamate/fmt.py` |
| §2 Tet tra lich am tu `public_test/calendar.csv` | `code/datamate/calendar_vn.py` |

## Co y chua lam
| Luat | Vi sao hoan |
| --- | --- |
| Gia von binh quan gia quyen theo lo nhap (§5) | rulebook §5 noi lay `gia von ghi tren dong ban`, khong tu tinh lai. Chi agent nao co cot do moi tra loi |
| §5 hieu ung tang gia | chi 1-2 shop co bang gia theo ngay; de agent shop do tu xu, khong code chung |
| D13 free text cot `Lam gi` cua dev_012 | agent dev_012 tu phan loai, ket qua ghi thanh tu dien trong logs |

## Quyet dinh tam, chua thanh ADR
| Quyet dinh | Ly do | Can ADR khong |
| --- | --- | --- |
| Agent la engine thay vi model <15B qua API | yeu cau cua phien nay la ra submission.jsonl, khong phai dung pipeline production | co -> adr/001 |
| Mot agent mot shop, khong canonical schema chung | 449 ten cot, 151 cot chi o 1 shop; canonical hoa 14 shop truoc khi tra loi la duong dai hon | co -> adr/002 |
| Abstain policy | EV 2p-1 | co -> adr/003 |
