# training_code: dữ liệu SFT cuối cho DataMate (Gemma 4 12B)

Thư mục này theo bố cục trong hướng dẫn Docker của BTC (§4, §8). Nó gồm dữ liệu train, toàn bộ code sinh dữ liệu, log
mọi lượt gọi teacher, và manifest có SHA-256 của từng file.

| Thư mục / file | Nội dung |
|---|---|
| `data/train.jsonl`, `data/val.jsonl` | dữ liệu SFT (prompt/completion kiểu TRL); **train 3862 mẫu, val 166 mẫu** |
| `data/*_meta.jsonl`, `data/stats.json` | thông tin từng mẫu; thống kê, số mẫu bị từng bộ lọc loại, số token |
| `data/README.md` | định dạng mẫu, cách train (`data/sft_lora.py`) |
| `data/POSTFILTER.json` | 13 mẫu bỏ sau khi đóng gói theo duyệt |
| `data/val_questions.jsonl` | mọi câu của shop và ngành giữ riêng, để đo độ chính xác thật |
| `data_generation/` | code sinh dữ liệu (`gen/`), các script chạy, code agent (`src/`) dùng để dựng prompt |
| `configs/` | config teacher, ghi chú riêng cho teacher (`teacher_note.md`), system prompt của agent (`prompt.md`) |
| `logs/teacher/*.tar.gz` | mọi record teacher: prompt và câu trả lời của từng lượt gọi API |
| `data_manifest.json` | mọi file: đường dẫn, số byte, SHA-256; số lượng; model sinh; commit git |

## Định dạng một mẫu

Prompt là đúng chuỗi message agent gửi lúc chạy thật: system prompt của agent, rồi rulebook, khối mô tả bảng của shop
và câu hỏi. Mẫu nhiều lượt có thêm các lượt trước cùng kết quả chạy của chúng. Completion là câu trả lời của teacher:

```
[CAUSE: …]  REASON: …  ASKED: …  RULES: …  PLAN: BIND/COMPUTE/CHECK  ```python … result = {...}```
```

**REASON là một phần của output.** Model chạy với thinking tắt và loss chỉ tính trên completion.

## Dữ liệu được sinh thế nào

1. **Câu hỏi**
   - **A:** câu hỏi train thật của BTC trên 27 shop (giữ riêng biz_108/110/130 làm val).
   - **R1/R2, G1/G2:** câu train thật giải lại trên bảng đã reskin, tức đổi tên, số và bố cục file. Riêng G1/G2 chọn
     các loại câu còn thiếu: kê đơn, nợ, nhập hàng, ca, khách...
   - **B9:** thế giới "luật bị đổi" (`--moved-only`): câu hỏi mà luật riêng của shop làm đáp án khác luật mặc định.
   - **forced:** mẫu sửa lỗi (`gen/forced.py`, `gen.teacher --prefill`). Lượt 1 sai do code viết theo các loại lỗi
     hay gặp (sai tên cột, cột trên nhầm bảng, nhãn trạng thái, tên mặt hàng, chuỗi không đóng, thiếu ngoặc khi ghép
     điều kiện, "không trả lời được" sai, sai kiểu percent); host chạy thật; teacher viết lượt sửa, đúng gold. Lượt
     dựng sẵn chỉ là lịch sử, không phải mẫu.
   - **B0–B8:** "thế giới riêng", mỗi câu một shop tự sinh (`gen/world.py`):
     - ngành và mặt hàng do model sinh;
     - rulebook riêng (75% theo kiểu train, 25% viết lại);
     - README riêng, 10% tên file mờ;
     - đáp án tính bằng oracle (`gen/oracle.py`), không phụ thuộc model.
   - **Val:** CW (37 ngành giữ riêng) và CS (3 shop thật giữ riêng).

   Không dùng dữ liệu public hay private test.
2. **Teacher:** DeepSeek V4.1 flash, chạy hai lượt.
   - Lượt 1 tắt thinking, temperature 0, `max_tokens` 8192 (`configs/config.final_nothink.yaml`).
   - Lượt 2 bật thinking, chỉ cho các câu lượt 1 sai (`configs/config.deepseek_direct.yaml`).
   - Teacher nhận thêm `teacher_note.md` trong system prompt. Prompt train được dựng lại không có ghi chú này.
3. **Lọc**
   - Chỉ giữ câu có đáp án cuối khớp gold.
   - Bộ lọc hình thức và code (`gen/sft.py`): REASON trước tiên, không lan man, các mục đúng thứ tự, không
     lambda/apply/vòng lặp theo dòng, không assert thừa, không đoán đơn vị, không viện dẫn ghi chú của teacher...
   - Bộ lọc khi đóng gói (`gen/package.py`): câu có đáp án không suy ra được từ file, và danh sách câu đúng nhờ may từ
     các đợt duyệt định kỳ (`gen/assets/final_drop_ids.txt`).
   - Cứ 100 câu, một agent đọc tay và đối chiếu với rulebook cùng dữ liệu.
4. **Số liệu:** 5.651 record teacher, 5.402 câu đúng, 3.969 câu qua lọc, cho ra 3.875 mẫu train và 166 mẫu val. Sau
   POSTFILTER còn **3862 mẫu train**, trong đó 576 mẫu là lượt sửa lỗi hoặc lượt sau look. Chi phí API khoảng $19.
   `scripts/augment_dates.py` có trong repo nhưng KHÔNG được áp dụng: câu hỏi giữ nguyên như lúc teacher giải.

Lệnh tái tạo: `data_generation/scripts/run_final_data.sh`, `run_more_data.sh`, `select_train_gap.py` +
`run_gap_data.sh`. Sau đó đóng gói:

```
python -m gen.package --teacher outputs/teacher/final/p1_* outputs/teacher/final/p2_* --out outputs/sft/final \
       --val-industries <các ngành val> --require-exact
```

## Train (khuyến nghị từ lượt duyệt cuối)

- Train **toàn bộ `data/train.jsonl`**. Không giới hạn các intent dễ, vì chúng chiếm khoảng 60% câu hỏi thật.
- LoRA r16 / alpha 32, lr 1e-4, cosine, effective batch 16, `--max-len 24576` (không mẫu nào bị bỏ vì quá dài).
- Một epoch là khoảng 60M token (prompt 55M, completion 4,7M).
  - Chạy 2 epoch nếu đủ GPU (khoảng 8 giờ H100), nếu không thì 1 epoch. Chốt số step trước khi chạy.
  - Không chạy quá 2 epoch.
- Lưu checkpoint mỗi 100 step và chọn theo `eval_loss` trên `val.jsonl`.

Trước khi chạy thật, kiểm tra:
- `--dry-run`: prompt render với `enable_thinking=False`, target kết thúc bằng `<turn|>`, không mẫu nào bị bỏ vì quá dài;
- chạy thử 5 step.

Sau khi train, đo trên `val_questions.jsonl` (shop thật biz_108/110/130 và các ngành giữ riêng).

## Giới hạn đã biết

- Rất ít mẫu lượt "look" và mẫu sửa kết quả bị host gắn cờ. Model sẽ ít khi xem dữ liệu trước khi giải.
- Một số loại câu hiếm còn mỏng: size, giỏ hàng, giao hàng, lãi, tồn kho tại ngày quá khứ.
- Các phiên bản luật phổ biến chiếm đa số, ví dụ "đơn đang giao vẫn tính". Model có thể nghiêng về chúng khi rulebook
  nói khác.
