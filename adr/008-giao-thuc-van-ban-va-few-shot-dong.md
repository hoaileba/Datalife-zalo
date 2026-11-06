# ADR 008: giao thức văn bản và few-shot động cho gemma 12B

**Trạng thái:** đề xuất, chờ Hoài duyệt. Số đo cuối nằm ở `EXP-20261104-03-text-protocol-fewshot`.

## Bối cảnh

Đã đo trên gemma 12B với prompt v5 (`EXP-20261104-02`):

- 10 câu mất 78 phút, score -3/10.
- 6/6 request có `tools` bị 429 upstream; 10/10 request không `tools` thành công trong 2,6–4,9s với 12.533 token prompt.
- 5/6 câu sai do model tự viết pandas, trong khi helper one-liner ra đúng 3/5 câu đã thử.

## Quyết định 1: bỏ native tool calling, dùng giao thức văn bản

Model trả lời bằng `READ <file>`, khối ```python, hoặc `FINAL <type>` kèm khối code. Harness parse lệnh đầu tiên và bỏ phần sau lệnh.

- **Pattern:** text-based ReAct (Yao et al. 2022, *ReAct: Synergizing Reasoning and Acting in Language Models*).
- **Đánh đổi:** đổi đảm bảo cấu trúc của tool schema lấy khả năng chạy trên mọi endpoint. Parser phải chịu được lỗi định dạng của model.
- **Phương án khác:** giữ `tools` và dùng key provider riêng (BYOK, tự mang key của nhà cung cấp): vẫn phụ thuộc một endpoint và cần anh tạo key. Chờ rate limit: đã thử, 78 phút cho 10 câu.

## Quyết định 2: few-shot động từ thư viện đã kiểm bằng gold

`oracle.py` sinh code helper từ mẫu câu trên `train/split/train_*`, chấm với gold, chỉ giữ cặp đúng vào `prompts/library.jsonl` (902 ví dụ, 48 mẫu). Lúc chạy, TF-IDF trên câu đã che tên riêng chọn 4 ví dụ thuộc 4 mẫu khác nhau, đặt ngay sau câu hỏi.

- **Pattern:** dynamic few-shot / kNN example selection (Liu et al. 2022, *What Makes Good In-Context Examples for GPT-3?*).
- **Đánh đổi:** chất lượng phụ thuộc độ phủ của thư viện. Câu ngoài 48 mẫu nhận ví dụ không liên quan.
- **Phương án khác:** bảng ví dụ tĩnh trong system prompt: v5 đã có 14 dòng, model vẫn tự viết pandas.

## Quyết định 3: gợi ý tên riêng và kỳ trong tin nhắn user

Harness khớp tên hàng, nhóm, khách, hoạt chất và kỳ bằng regex rồi ghi vào `Nhận ra trong câu`.

- **Pattern:** schema linking (bước nối từ trong câu với giá trị trong dữ liệu của NL2SQL).
- **Đánh đổi:** regex sai sẽ dẫn model đi sai. Chưa đo riêng tác động của bước này.

## Quyết định 4: không nhúng code theo từng shop vào agent

`EXP-20261029-01` có khoảng 10.000 dòng code theo từng shop public. Chỉ đọc để lấy luật chung, không nhúng vào agent, vì nhúng vào thì điểm public đẹp mà không phản ánh agent trên shop lạ.

## Quyết định 5: `unanswerable` bị từ chối một lần nếu chưa chạy code

Train có 60/2550 câu (2,4%) đáp án `unanswerable`, nên model bỏ cuộc sớm phần lớn là sai và mất 1 điểm. Harness từ chối lần đầu trừ khi code đã chạy hoặc helper báo `shop has no`.

## Việc còn treo

- 6 shop train chưa dựng được `lines`: biz_106, 107, 109, 113, 124, 126.
- `intents.py` trên train đạt 1725/2550 (67,6%) không cần LLM. Nếu gemma thấp hơn con số này thì phải bàn lại vai trò của LLM.

## Bổ sung sau khi đọc log `EXP-20261104-03`

Anh Hoài chốt: từ điển tất định trước, LLM viết lại câu để sau nếu số đo còn cần.

### Quyết định 6: từ địa phương đi qua từ điển, không qua LLM

`question_norm.py` mở `bữa`, `củ`, `mô`, `ni`, `nhut`, `mik`, `wan`; prompt v7 ghi cùng các từ đó. Từ địa phương gây sai 2/36 câu nên chưa đáng thêm một lượt gọi LLM. Đánh đổi: chỉ phủ từ đã gặp; 266/1000 câu public có từ không có trong train.

### Quyết định 7: đưa nhóm hàng và đơn vị thật của shop vào tin nhắn user

Để model tự nối cách gọi trong câu với giá trị trong dữ liệu, ví dụ "điện thoại cũ" với nhóm `máy cũ`. Pattern: schema linking. Chưa đo riêng tác động.

### Quyết định 8: hết lượt mà chưa có code chạy được thì bỏ trống

Rulebook §9: bỏ trống 0 điểm, sai -1. Train có 60/2550 câu (2,4%) là `unanswerable`, nên kết luận `unanswerable` khi chưa có code nào chạy được phần lớn là sai. `no ... matches` cũng không được coi là thiếu dữ liệu.

### Quyết định 9: không nộp giá trị không qua code

`FINAL` là giá trị thuần phải trùng với output đã chạy, nếu không sẽ bị từ chối. Lý do: `q_10a0c4fec3d2` nộp thẳng `True` không qua tính toán.

### Việc còn treo

- `stock_big` trên nhà thuốc nhiều cấp đơn vị: biz_121 ra [681, 9], gold [16, 9].
- Nhóm khách biz_128: 136238500, gold 138616000, chưa rõ nguyên nhân.
- `repeat_vehicles` dev_012: 44, tham chiếu 33, chưa rõ luật.
- Trả góp dev_014 chưa có helper.
