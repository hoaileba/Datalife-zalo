# ADR 015: Thư viện ví dụ chỉ từ train_*, thêm lời giải agent đã đúng

Trạng thái: Hoài chốt ngày 2026-11-07, chờ duyệt chi tiết

## Bối cảnh

Thư viện cũ 967 ví dụ dựng trước EXP-03/04, có 3 câu test_* (tập chỉ dùng để đo). Oracle chỉ sinh ví dụ cho loại câu nó có luật.

## Quyết định

1. `prompts/library.jsonl` dựng lại từ oracle train mới nhất, chỉ câu `train_*` oracle đúng: 1109 ví dụ, 55 loại.
2. Thêm 98 ví dụ từ code FINAL agent đúng theo gold trên `train_*`; loại câu gán theo khung code, trùng khung với ví dụ cũ thì dùng chung loại.
3. Agent loại chính câu đang hỏi khỏi ứng viên (`exclude`), để đo trên train không tự thấy đáp án.

## Pattern và đánh đổi

Train/test separation cho few-shot. Đánh đổi: ví dụ từ agent có thể đúng nhờ may; chỉ lấy câu đúng theo gold và code một dòng.

## Đo sau khi áp dụng

Độ chính xác tìm ví dụ không đổi (public top-1 81,6%); tác dụng chỉ ở câu thiếu mẫu, đo qua EXP-20261107-04.

EXP-20261107-04, 1000 câu public với prompt v10: nhóm TF-IDF chắc (825 câu, chỉ thư viện tác động) được 14, mất 12, ΔPA +0,001, nằm trong dao động. Ví dụ do agent tạo mang lại 3 câu được và 1 câu mất (`delivery_rounds` lên top-1 thay cho `delivered_quantity`). Giữ, vì cách này tách train/test sạch hơn, không phải vì tăng điểm.
