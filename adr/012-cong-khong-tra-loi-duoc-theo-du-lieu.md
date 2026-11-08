# ADR 012: Cổng "không trả lời được" chỉ dựa trên dữ liệu

Trạng thái: Hoài yêu cầu làm ngày 2026-11-07, chờ duyệt chi tiết

## Bối cảnh

76 câu public gemma còn sai: 18 câu đáp án là unanswerable mà model vẫn trả số, 5 câu code lỗi rồi model nộp unanswerable (bị −1, bỏ trống chỉ mất 0). Luật theo từ khoá câu hỏi dễ overfit public.

## Quyết định

1. `Shop._require_period`: kỳ hỏi nằm hẳn ngoài khoảng ngày có dữ liệu bán (trước ngày bán đầu tiên hoặc sau as_of) thì helper báo `shop has no sales data in ...: answer is unanswerable`.
2. Agent: model nộp `FINAL unanswerable` mà đã có lỗi code không phải `shop has no` / `no ... matches`, và chưa helper nào báo thiếu dữ liệu, thì đổi thành bỏ trống (`abstain`).
3. Không làm cổng theo từ khoá (tính từ, giới tính, địa chỉ) trong code.

## Pattern và đánh đổi

Fail-safe default: không chắc thì chọn kết quả ít thiệt nhất (0 thay vì −1). Đánh đổi: câu thật sự không trả lời được mà code model lỗi sẽ thành bỏ trống, mất +1 có thể có.

## Phương án đã loại

- Cổng theo danh sách từ khoá rút từ public: overfit.
- LLM liệt kê "thông tin cần" rồi so với cột: trường đó quá nhiễu (ADR 011).

## Đo sau khi áp dụng

Xem EXP-20261107-03.
