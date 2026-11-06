# Batch plan — EXP-20261029-01-public-test-submission

Vòng 1 chạy 15 agent song song và **chết hết vì session rate limit** (429, reset 14:50 +07).
Vòng 2 chạy theo batch 3 agent.

## Vì sao 3 agent một batch

Vòng 1: 15 agent Opus song song, mỗi agent ingest 0.3–24 MB Excel và lập luận trên 40–129 câu.
Burn hết limit trong ~20 phút wall time, và lúc chết **chỉ 3 shop có file đáp án**. Tức là công
việc cho 11 shop còn lại **lớn hơn một cửa sổ limit**, không phải nhỏ hơn.

Batch 3 agent ≈ 1/5 tải của vòng 1 → ước lượng **2 batch một cửa sổ limit**.

## Đã xong, nhưng CHƯA kiểm (vớt từ vòng 1)

| Shop | Câu | Trạng thái |
| --- | --- | --- |
| `dev_002` | 41 | script chạy ra 41 đáp án. **Thiếu bước D (tự kiểm) và thiếu notes** — agent chết trước khi viết |
| `dev_009` | 21 | 21 đáp án, 18 `number` + 3 `date`. **Thiếu notes.** Đáng ngờ: shop này lẽ ra nhiều `unanswerable` |
| `dev_011` | 40 | script chạy ra 40 đáp án, agent kịp báo bước A+B đầy đủ. **Thiếu notes file** |

Ba shop này phải có **một batch verify riêng**, không tính là xong.

## Batch

| Batch | Shop | Câu | Lý do xếp nhóm |
| --- | --- | --- | --- |
| 1 | `dev_003`, `dev_006`, `dev_008` | 129 + 111 + 99 = 339 | ba shop nặng nhất, chạy khi cửa sổ còn mới |
| 2 | `dev_004`, `dev_005`, `dev_001` | 96 + 87 + 87 = 270 | nặng vừa; `dev_005` nhà thuốc nhiều luật ngành |
| — | **DỪNG, chờ lệnh Hoài** | | ước lượng ~80% cửa sổ |
| 3 | `dev_014`, `dev_007`, `dev_010` | 63 + 60 + 59 = 182 | |
| 4 | `dev_013`, `dev_012`, calibration `biz_112` | 57 + 50 + 100 | calibration là số accuracy thật duy nhất |
| 5 | verify `dev_002`, `dev_009`, `dev_011` | 102 | bù bước D còn thiếu |

## Không đo được cái gì

**Tôi không đọc được mức dùng limit của anh.** Không có tool nào trong phiên này trả về con số đó.
"Chạy đến 80%" là thứ tôi chỉ **ước lượng** được từ tải, không đo được.

Số thật duy nhất: lệnh `/usage` trong terminal của anh. Sau mỗi batch tôi báo cáo, anh xem `/usage`
rồi quyết chạy tiếp hay dừng.

## Mỗi batch kết thúc bằng

```
cd $E/code && python3 merge.py
```

Merge luôn ghi đủ 1000 dòng: shop nào chưa có đáp án thì ghi `abstain` (0 điểm, không âm). Nên
`out/submission.jsonl` **lúc nào cũng là file nộp được**, chỉ là coverage thấp.
