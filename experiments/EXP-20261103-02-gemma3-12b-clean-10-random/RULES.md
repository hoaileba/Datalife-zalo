# RULES — EXP-20261103-02

## Biến thay đổi so với parent (EXP-20261103-01)

Một gói duy nhất là "môi trường đã dựng sẵn":
1. Chuẩn hoá chạy trước (`docs/06`): bảng sạch ở `work/clean/<shop>/`, tên cột chuẩn, dòng tổng / header lặp / dòng trùng đã tách.
2. `{{context}}` thêm PROFILE. Toolkit thêm `load`, `in_period`, `on_day`.
3. Prompt viết lại theo bảng sạch; ví dụ dùng tên cột chuẩn. Ví dụ "tháng nào" thêm vì gemma trả số tiền ở parent.

Model, seed, tool_choice, 10 câu, tham chiếu, max_turns, stuck_after giữ nguyên.

## Luật rulebook được code hoá

Trong tầng chuẩn hoá (`modules/normalize.py`): rulebook §8 về ô trống dòng sau của nhóm, dòng trùng trong một đơn, khách lẻ, quy trạng thái về 4 trạng thái.

## Cố ý chưa làm

- Suy trạng thái từ Ghi chú khi không có cột trạng thái.
- Quy đổi đơn vị, join danh mục, mở rộng tên ghi tắt: model tự làm từ bảng danh mục.
- Log gọn của docs/04.

## Quyết định tạm chưa thành ADR

- Bỏ README khỏi bước map cột: đo trên 6 bảng, chọn đúng loại bảng 6/6 so với 5/6 khi có README đặt sau, và README đặt trước làm model đề xuất cột ngoài bảng.
- Model map cột `qwen/qwen3-14b` reasoning off; model trả lời `gemma-3-12b`.
