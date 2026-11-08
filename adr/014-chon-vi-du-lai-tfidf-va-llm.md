# ADR 014: Chọn ví dụ bằng TF-IDF, LLM xếp lại khi TF-IDF không chắc

Trạng thái: Hoài chốt ngày 2026-11-07 (dùng chính gemma), chờ duyệt chi tiết

## Bối cảnh

76 lỗi public: 13 câu có ví dụ đúng ở hạng 2–4 mà model chép hạng 1. Đo offline trên 570 câu public oracle giải đúng: TF-IDF top-1 đúng loại 81,6%, đúng hàm chính 89,5%; loại đúng nằm trong 8 ứng viên 98,8%.

## Quyết định

1. TF-IDF lấy 8 ứng viên, mỗi loại câu một ví dụ (`Library.scored`).
2. Chênh điểm cosine giữa ứng viên hạng 1 và hạng 2 dưới 0,05 thì gemma chọn lại trong 8 ứng viên (`example_rerank.rerank`); ví dụ được chọn lên đầu, 4 ví dụ đầu đưa vào prompt.
3. Ngưỡng 0,05 chọn trên bộ đo thư viện (câu train), không chọn trên public.

## Pattern và đánh đổi

Cascade (rẻ trước, đắt khi không chắc) với LLM làm reranker. Đo offline theo hàm chính: public 89,5% → 94,2%, thư viện 94,3% → 95,7%. gemma xếp lại mọi câu thì public tăng nhưng thư viện giảm (93,3%), nên chỉ hỏi khi TF-IDF không chắc. Đánh đổi: thêm một lời gọi LLM ở khoảng 6–18% số câu.

## Phương án đã loại

- Embedding hoặc reranker tự train: Hoài chọn dùng gemma; model của Hoài train cho văn bản luật, chưa đo trên miền này.
- gemma xếp lại mọi câu: kém TF-IDF trên bộ đo thư viện.

## Đo sau khi áp dụng

EXP-20261107-04, 1000 câu public, lenient scorer, so với EXP-03 cuối (cùng câu, khác prompt v11 và thư viện):

| Nhóm | Câu | Được | Mất | ΔPA |
|---|---|---|---|---|
| gemma đổi top-1 | 109 | 14 | 6 | +0,017 |
| gemma giữ top-1 | 66 | 4 | 2 | +0,003 |

Gemma được hỏi ở 175/1000 câu (17,5%), không lỗi API.

Đo lại với prompt v10 (bỏ PA1), 1000 câu: tổng +0,876 so với +0,858. Nhóm gemma đổi top-1: 109 câu, được 15, mất 5, ΔPA +0,018; nhóm gemma giữ top-1: −0,001. Phần tăng gần hết đến từ bước xếp lại.
