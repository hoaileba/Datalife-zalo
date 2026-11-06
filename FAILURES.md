# FAILURES

Đường mòn đã đi. Đọc trước khi đi một hướng mới.

## 2026-10-31 — qwen3-14b chạy harness shop agent, 20 câu public (EXP-20261031-01)

- **Nhiệm vụ:** dùng `src/datamate_agent` + qwen/qwen3-14b qua OpenRouter trả lời 20 câu public, so với đáp án Claude (0,994 public).
- **Đã làm:** 10 shop agent, batch 3, executor docker, `allow_abstain: false`, max_turns 60. Chi phí $0,81.
- **Vì sao thất bại:**
  1. Đồng ý với Claude 0/20. Model bịa id câu hỏi (`q1/q2/q3`), dùng id shop khác, viết tay file đáp án với số bịa (12345, 54321), lặp suy biến 25 lượt.
  2. Lỗ hổng harness: Verifier chỉ so file đáp án trước/sau khi chạy lại script, nên script KHÔNG ghi file thì file viết tay vẫn qua. 4/6 shop "verified" là giả. Đã sửa (dời file trước khi chạy lại, chặn `write_file` vào `out/answers/`).
- **Bài học:** cổng kiểm phải chứng minh *output sinh ra từ đâu*, không chỉ *output không đổi*. Và "verified" chưa bao giờ nghĩa là "đúng": luôn so với một tham chiếu.

## 2026-11-01 — harness v2 + qwen3-14b, 20 câu public (EXP-20261101-01)

- **Nhiệm vụ:** chạy lại 20 câu với harness v2 (khung script, đường dẫn chung, pool, phát hiện kẹt, Verifier sửa).
- **Đã làm:** như parent, chỉ đổi harness. 37,1 phút, $0,75.
- **Vì sao thất bại:** 10/10 shop `stuck`, 0 đáp án hợp lệ. Model **không ghi vào file script lần nào** (0/10 shop): viết
  và chạy `answer()` trong code nháp rồi gọi `finish`, Verifier chạy khung gốc → lỗi "not answered yet" 3 lần → dừng.
  Một số shop ghi file đáp án qua code nháp; merge lúc đó còn gộp cả shop chưa verify (đã sửa).
- **Bài học:** đừng thiết kế giao kèo theo cách *mình* làm việc (sửa file rồi chạy) khi model nhỏ làm việc theo cách khác
  (chạy đoạn code). Đo hành vi thật của model trước (đếm loại tool call), rồi mới chọn giao kèo. Và mọi đường ghi ra
  đáp án — kể cả qua code nháp — đều phải đi qua cùng một cổng.

## 2026-11-03 — qwen3-14b và gemma-3-12b trên dữ liệu thô, 10 câu public (EXP-20261101-02, EXP-20261103-01)

- **Nhiệm vụ:** chấm hai model nhỏ với tool `submit` và prompt 6 phần, trên 10 câu random, so với Claude.
- **Đã làm:** hai nhánh vi/en cho mỗi model, không có tiền xử lý. Tổng $0,78.
- **Vì sao thất bại:** 0/10 câu khớp Claude ở cả 4 nhánh. Khoảng 76% lần `submit` bị từ chối (qwen) là lỗi dữ liệu thô: ngày trộn định dạng, sai tên cột hoặc sheet có dấu, tiền là chuỗi. gemma thêm lỗi viết code (quên import, sai thụt lề). `verified` vẫn chứa đáp án sai vì Verifier chỉ kiểm format.
- **Bài học:** đừng đo model khi môi trường còn bắt model tự làm sạch dữ liệu ở mọi câu: số đo khi đó chủ yếu phản ánh dữ liệu thô. Dựng môi trường trước và có **đối chứng dương** (chạy đúng công thức trên bảng sạch ra đáp án Claude) rồi mới đo model.

## 2026-11-03 — harness cũ với khuôn hàm `answer` trên gemma (EXP-20261103-02) và chạy không theo dõi

- **Nhiệm vụ:** chạy 10 câu trên bảng sạch.
- **Đã làm:** chạy cả lần 10 câu với khuôn `answer(question, clock)` mà chưa thử trên một câu; sau đó chờ thông báo trong khi một lần chạy treo.
- **Vì sao thất bại:** 0/16 lần `submit` được nhận, 9 là `IndentationError`; model tính đúng ở dạng script nhưng gói hỏng thành hàm. Lần chạy sau treo khoảng 1 giờ, không có timeout mà không ai thấy.
- **Bài học:** đổi model hoặc giao kèo thì thử một câu trước. Lần chạy nền phải có timeout và phải chủ động kiểm tiến độ. Đừng thêm khuôn mà model nhỏ phải tuân theo khi nó có thể chỉ cần in ra kết quả.

## 2026-11-03 — vòng sửa lỗi không tác dụng (EXP-20261103-04)

- **Nhiệm vụ:** để agent tự sửa khi code lỗi.
- **Đã làm:** gửi nguyên traceback cho model.
- **Vì sao thất bại:** 55/77 cặp code liên tiếp y hệt, 7/20 câu hết turn. Phát lại: traceback 861 ký tự thì lặp 2/2, dòng lỗi cuối thì sửa 2/2.
- **Bài học:** "có đưa lỗi cho model" không có nghĩa là "model dùng được lỗi". Đo tỉ lệ code lặp sau mỗi lần sửa vòng lặp, và phát lại hội thoại thật thay vì đoán.

## 2026-11-04 — agent gemma tự chuẩn hoá dữ liệu, và mapping cột sai im lặng (prompt v3, EXP-20261103-03)

- **Nhiệm vụ:** để gemma-3-12b tự đọc, tự chuẩn hoá vào `norm/` rồi tính; trước đó dùng bảng sạch do LLM map cột.
- **Đã làm:** chạy 2 case với prompt v3. Sau đó dựng lại bảng sạch cũ và đối chứng rộng hơn với đáp án Claude.
- **Vì sao thất bại:** cả 2 case sai, `norm/` rỗng: gemma lặp `read_data` hoặc kẹt ở parse tiền. Riêng bảng cũ: `dev_007` lấy tiền cấp đơn làm `line_amount` (lệch hơn 4 lần), `dev_013` mất `order_date`. Đối chứng 7/7 hôm trước không phát hiện được, nên gemma đã bị đo trên bảng sai.
- **Bài học:** đối chứng dương phải phủ đủ mọi shop, không chỉ vài câu. Thấy dữ liệu có template thì đo trước xem có tra cứu tất định được không, rồi mới dùng LLM. Regex trạng thái phải có ranh giới từ: `chuyen` chứa `huy`.

## 2026-11-04 — Agent gemma dùng native tool calling trên OpenRouter

- **Nhiệm vụ:** chạy gemma 12B với `tools` và `tool_choice="required"` trên public.
- **Hành động:** thêm retry 429, chờ 20s, parallel 2, tăng số lần thử lên 60.
- **Vì sao thất bại:** mỗi request có `tools` chỉ đi được vào đúng một endpoint DeepInfra đang bị rate limit upstream. Cùng cỡ prompt, không `tools` thì 10/10 request thành công trong 2,6–4,9s. Retry chỉ che triệu chứng.
