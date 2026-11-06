# RULES — EXP-20261103-05

## Thay đổi so với parent

Một biến: khi code lỗi, model chỉ nhận dòng lỗi cuối thay vì traceback; traceback đầy đủ vẫn ghi trong log. Thêm lưu `<id>.conversation.json` (không ảnh hưởng model).
Mẫu câu khác parent nên điểm không so trực tiếp; so số đo vòng lặp.

## Luật rulebook được code hoá

Như parent.

## Cố ý chưa làm

Chặn gọi code y hệt; cổng `conclude` chấp nhận output tự in; bắt buộc dùng is_revenue, status_norm.

## Quyết định tạm chưa thành ADR

Chỉ gửi dòng lỗi cuối: căn cứ phát lại n=2 mỗi kiểu ở parent.
