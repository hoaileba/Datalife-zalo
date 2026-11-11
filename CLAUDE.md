# DataMate v4: luật làm việc

Dự án: Zalo AI Challenge 2026, DataMate (hỏi đáp tiếng Việt trên dữ liệu bảng), chỉ một luồng **code agent**. Đề bài: `docs/zac/`. Bản đồ code: `MAP.md` (đọc trước khi sửa). Quyết định: `DECISIONS.md`.

## Public test: CHỈ ĐO, KHÔNG ĐỌC
- Không đọc, in, grep, mở nội dung của `data/public_test/**` (câu hỏi, đáp án, dữ liệu cửa hàng, rulebook), trừ khi người dùng cho phép rõ trong phiên đó và chỉ trong phạm vi được cho phép.
- Chạy trên public chỉ xem số tổng hợp in ra. Không đọc log/trace của lượt chạy public nếu người dùng chưa cho phép.
- Không chỉnh luật, prompt, ví dụ, ngưỡng theo nội dung public. Mọi chỉnh sửa dựa trên train hoặc dữ liệu tự tạo.
- Không ghi nội dung public vào code, test, tài liệu, memory.

## Chi phí
- Mỗi lượt dev tối đa **6 câu**. Chạy tập lớn hơn phải được người dùng cho phép rõ, kèm ước lượng số lượt gọi và thời gian.
- Model: Gemma 12B qua vLLM (`VLLM_BASE_URL`), tối đa 2 luồng song song; thinking tắt, `temperature=0`, `seed=0`.
- Phần không gọi model (test, replay, đọc dữ liệu) chạy thoải mái.

## Môi trường
- Python: `/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python`, đặt `PYTHONIOENCODING=utf-8`.
- Dữ liệu: `data/train`, `data/public_test` (không đưa vào git).
- Không sửa `src/` khi một lượt đo đang chạy.
