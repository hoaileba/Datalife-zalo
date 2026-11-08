# ADR 013: Hợp đồng dạng đáp án ở FINAL

Trạng thái: Hoài yêu cầu làm ngày 2026-11-07, chờ duyệt chi tiết

## Bối cảnh

18 câu public sai dạng đáp án: "5 khách" trả 1 người, "tháng nào" trả số tiền, "ví điện tử được bao nhiêu" trả danh sách 2 số.

## Quyết định

1. Dạng đáp án và số phần tử lấy từ phân tích câu hỏi (ADR 011), hiện cho model là "Đáp án cần: ...".
2. `agent.shape_mismatch` chỉ bắt lệch rõ: cần ≥ 2 phần tử mà số phần tử khác; cần tên, ngày, tháng mà ra số hoặc danh sách; cần một số mà ra danh sách ≥ 2; cần đúng sai mà không phải bool.
3. Lệch thì trả lỗi cho model sửa, tối đa một lần mỗi câu; lần sau nhận đáp án như cũ.

## Pattern và đánh đổi

Design by Contract ở biên LLM → đáp án. Đánh đổi: phân tích sai dạng thì có thể đẩy model sửa một đáp án đúng thành sai; giới hạn một lần để không lặp.

## Phương án đã loại

- Suy dạng đáp án bằng regex trên câu hỏi: overfit cách hỏi của public.
- Từ chối nhiều lần: model nhỏ dễ lặp tới hết lượt.

## Đo sau khi áp dụng

Xem EXP-20261107-03.
