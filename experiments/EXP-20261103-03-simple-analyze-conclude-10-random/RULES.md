# RULES — EXP-20261103-03

## Thay đổi so với parent

Bỏ harness cũ: `clock`, khuôn hàm `answer`, Verifier chạy lại script, lược context, phát hiện stuck, ngân sách token, log nhiều file. Hoài yêu cầu.

Luồng mới, một câu một agent (`code/src/datamate_agent/simple.py`, `prompts/simple.md`):
1. `run_python`: chạy code phân tích, nhiều lần. `conclude` bị từ chối nếu chưa có lần chạy nào in ra kết quả.
2. `conclude(findings, logic, answer_type, ok)`: `ok=false` thì phân tích tiếp; `unanswerable` kết thúc tại đây.
3. `run_final(code)`: đáp án là dòng in cuối của code, parse theo `answer_type`, sai format thì trả lỗi cho model sửa.

Tối đa 12 turn. `--parallel 1`, thử lại 10 lần khi gặp 429, timeout mỗi request 300 s.

## Luật rulebook được code hoá

Trong tầng chuẩn hoá (`modules/normalize.py`): §8 về ô trống dòng sau, dòng trùng trong đơn, sổ không có cột trạng thái, 4 trạng thái. Rulebook chép nguyên văn vào system prompt.

## Cố ý chưa làm

- Tính ngày lịch âm trong sandbox: câu Tết phải tự suy, biết trước sẽ khó.
- Đặt lại tên bảng gộp (`sales_banhang_thang01_2025` chứa 17 tháng).
- Lỗi chuẩn hoá ngoài mẫu: dev_008 note ← Bàn; dev_006, dev_010 bảng dòng hàng không có status_norm; dev_013 chưa giao → huỷ.

## Quyết định tạm chưa thành ADR

- `simple.py` và 3 pha chưa có doc/ADR: Hoài ra lệnh trực tiếp.
- 10 câu không còn mù: đã dùng ở đối chứng dương và 2 lần chạy thử. Điểm này chỉ để so tiến bộ.
- Giá token như parent: input $0,05/M, output $0,15/M.
