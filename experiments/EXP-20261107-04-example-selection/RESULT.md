# RESULT

Chọn ví dụ bằng TF-IDF rồi để gemma chọn lại khi TF-IDF không chắc (ADR 014), dùng thư viện chỉ dựng từ câu `train_*` (ADR 015). Prompt v11 (ADR 016) đo âm và đã bỏ. Bản giữ lại: prompt v10 + PA2 + PA3.

## Số (1000 câu public, gemma-3-12b-it, lenient scorer)
| Bản | PA | Đúng | Sai | Trống |
|---|---|---|---|---|
| EXP-03 cuối | +0,858 | 924 | 66 | 10 |
| EXP-03 file nộp | +0,859 | 924 | 65 | 11 |
| v11 + PA2 + PA3 (`run/public1000`) | +0,849 | 918 | 69 | 13 |
| v10 + PA2 + PA3 (`run/public1000_v10`) | +0,876 | 936 | 60 | 4 |
| File nộp mới `out/submission.jsonl` | +0,878 (strict +0,850) | 936 | 58 | 6 |

Không có câu nào lỗi API ở cả hai lần chạy.

## Tách theo cách chọn ví dụ (v10 + PA2 + PA3 so với EXP-03 cuối)
| Nhóm | Câu | Được | Mất | ΔPA |
|---|---|---|---|---|
| gemma đổi top-1 | 109 | 15 | 5 | +0,018 |
| gemma giữ top-1 | 66 | 2 | 2 | −0,001 |
| TF-IDF chắc (chỉ thư viện tác động) | 825 | 14 | 12 | +0,001 |

- PA2 mang lại gần hết phần tăng.
- PA3 cho kết quả trung tính, nằm trong dao động.
- PA1 (v11): 38/47 câu mất có top-1 đã đúng hàm mà model không theo. Số câu model tự viết code tăng từ 95 lên 119. Đã bỏ PA1, trả `agent.py` về `code/src_before_pa1`.

## Script
`code/score_public.py <run>`, `split_cause.py`, `follow_rate.py`, `show_flips.py`, `make_submission.py` (chép từ EXP-03).
