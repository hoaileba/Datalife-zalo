# ADR 017: Ví dụ chỉ lấy từ shop khác

Trạng thái: agent tự quyết khi chạy 1000 câu train, chờ Hoài duyệt

## Bối cảnh

Thư viện (ADR 015) dựng từ câu `train_*`. Khi chạy trên câu train, `exclude` chỉ bỏ chính câu đang hỏi; câu khác cùng shop (tên hàng, tên khách thật của shop đó) vẫn lên làm ví dụ, trong khi gợi ý ghi "câu đã làm đúng ở shop khác". 481/1000 câu train mẫu có nguyên văn trong thư viện.

## Quyết định

1. `Example.shops`: các `business_id` có câu này, nối từ `train/questions.jsonl` theo nguyên văn câu hỏi (1207/1207 nối được; `library_curated.jsonl` để trống).
2. `Library.scored(..., shop=)` bỏ ví dụ của shop đang hỏi; `pick_examples` truyền `business_id`.

## Pattern và đánh đổi

Leave-one-group-out ở tầng few-shot: đo trên train giống điều kiện private (shop chưa thấy). Public không đổi: 0/1000 câu đổi ứng viên. Train: 341/1000 câu đổi ứng viên, 91 đổi top-1. Đánh đổi: thư viện lớn hơn sau này phải giữ trường `shops` khi dựng lại.

## Đo sau khi áp dụng

EXP-20261107-05.
