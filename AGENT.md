# zalo-2026 — luật repo

Bài toán: DataMate, trả lời câu hỏi tiếng Việt trên dữ liệu bán hàng của 44 shop. Phân tích ở `docs/01-phan-tich-du-lieu.md`, plan ở `docs/02-plan-kien-truc.md`. Đọc hai file đó trước khi bàn thiết kế.

Chấm điểm: đúng **+1**, sai **−1**, bỏ trống **0**. Mọi quyết định trong repo này bám vào con số đó, không bám accuracy.

## Agent `experiment-runner`

Agent duy nhất được phép chạy thực nghiệm trong repo này. Tồn tại để **mỗi con số đưa ra đều truy lại được tới code, dữ liệu và luật đã sinh ra nó**.

### Nó là gì

Một lab notebook có kỷ luật: nhận một yêu cầu thực nghiệm, chạy, và để lại một thư mục đóng kín chứa đủ thứ để người khác chạy lại ra đúng số đó. Pattern: **immutable experiment log** — đã đóng thì không sửa, muốn đổi thì mở thực nghiệm mới trỏ về cái cũ.

### Chạy nó như thế nào

Hoài ra một yêu cầu thực nghiệm. Agent không tự mở thực nghiệm.

Yêu cầu tối thiểu phải có: **mục đích** và **số nào sẽ được đo**. Thiếu một trong hai thì agent hỏi lại, không đoán.

### Tại sao lại có nó

Ba lý do đo được, từ `docs/01`:

1. 49 case dữ liệu bẩn đã xác nhận. Phần lớn sai **im lặng** — số vẫn ra, chỉ là sai. Không có nhật ký thì không phân biệt được "thuật toán kém" với "parse sai một cột".
2. Kết quả phụ thuộc model < 15B qua API: cùng input có thể ra khác output. Không ghi `seed`, `model`, `prompt` thì không tái lập được.
3. Hàm mất mát không đối xứng (−1 cho sai). Một thay đổi làm accuracy tăng mà điểm giảm là chuyện thường. Phải so được hai lần chạy với nhau, nên cả hai phải ghi cùng một bộ số.

## Bố cục một thực nghiệm

```
experiments/
├── INDEX.md                        append-only, một dòng một thực nghiệm
└── EXP-<YYYYMMDD>-<NN>-<slug>/
    ├── manifest.json               khai báo trước khi chạy
    ├── RULES.md                    luật áp dụng cho riêng lần chạy này
    ├── STEPS.md                    nhật ký append-only trong lúc chạy
    ├── RESULT.md                   số đo + kết luận, viết sau khi chạy
    ├── code/                        snapshot code đã chạy, không phải symlink
    ├── logs/                        stdout, stderr thô, không biên tập
    └── out/                         artifact: submission.jsonl, bảng số, parquet mẫu
```

ID: `EXP-20261029-01-scorer-baseline`. Ngày là ngày mở, `NN` tăng dần trong ngày, slug kebab-case.

### `manifest.json` — khai báo **trước** khi chạy

| Field | Nghĩa |
| --- | --- |
| `id` | trùng tên thư mục |
| `opened_at` | ISO 8601 |
| `goal` | một câu, mục đích |
| `hypothesis` | điều dự đoán sẽ xảy ra, hoặc `null` nếu đây là thực nghiệm đo mốc |
| `metrics` | danh sách tên số sẽ đo, khai trước khi biết kết quả |
| `dataset` | đường dẫn + số dòng. Tập đánh giá mặc định: `train/split/test_questions.jsonl` (450 câu) |
| `phase` | P0…P6 theo `docs/02` |
| `model` | tên model, hoặc `null` nếu không dùng model |
| `seed` | số, bắt buộc nếu có bất kỳ thành phần random |
| `parent` | id thực nghiệm trước nếu đây là biến thể của nó, hoặc `null` |
| `status` | `open` → `closed` → (`failed`) |

Là Pydantic model: validated, frozen, cấm field lạ. Khai `metrics` trước khi biết kết quả là có chủ đích — nó chặn việc chọn số đẹp sau khi đã thấy kết quả.

### `RULES.md` — luật áp dụng cho riêng lần chạy này

Không phải bản copy của `rulebook.md`. Chỉ ghi ba thứ:

1. Luật nào trong `rulebook.md` được code hoá trong lần chạy này, và ở file nào.
2. Luật nào **cố ý chưa làm**. Ghi rõ, vì nó giải thích phần sai còn lại.
3. Quyết định tạm nào đã lấy mà chưa thành ADR.

### `STEPS.md` — nhật ký trong lúc chạy

Append-only. Mỗi bước một khối, ba dòng, đúng khuôn báo cáo đang dùng:

```
## 2026-10-29T14:03:12 — bước 3/7
Đã làm:    chạy ingest trên 30 shop train, lệnh ở logs/03-ingest.cmd
Kết quả:   28/30 pass invariant. biz_105, biz_117 fail invariant "order_total khớp"
           -> lệch trung bình 1.2% số đơn, nghi do dòng số lượng âm (case 10)
Bước tiếp: bước 4 — tách nhánh xử lý trả hàng dạng số lượng âm
```

Viết **trong lúc** chạy, không viết lại sau khi xong. Một bước là thứ kiểm chứng được: file đã ghi, test đã chạy, số đã tính ra.

### `RESULT.md` — viết sau khi chạy

Bắt buộc có, kể cả khi thực nghiệm thất bại.

| Mục | Nội dung |
| --- | --- |
| Số đo | bảng, đúng các `metrics` đã khai trong manifest, không thêm không bớt |
| Ba số luôn in cùng nhau | **điểm**, accuracy, coverage. In riêng một số là báo cáo vô dụng |
| So với parent | nếu có `parent`, bảng hai cột cạnh nhau |
| Có đạt milestone | milestone của phase đó trong `docs/02`, đạt hay không, không dùng chữ "gần đạt" |
| Kết luận | giả thuyết đúng, sai, hay không kết luận được |
| Việc còn treo | đi vào phase nào |

## Luật bắt buộc

1. **Khai trước, chạy sau.** `manifest.json` phải tồn tại và `status: open` trước lệnh chạy đầu tiên. Khai `metrics` sau khi thấy kết quả là tự lừa mình.
2. **Mọi số phải kèm lệnh đã chạy.** Lệnh lưu vào `logs/<NN>-<ten>.cmd`, output thô vào `logs/<NN>-<ten>.log`. Không có log thì số đó không được viết vào `RESULT.md`.
3. **`code/` là snapshot, không phải symlink.** Code trong source tree sẽ đổi; thư mục thực nghiệm phải chạy lại được sau khi source đã đi xa.
4. **Logs không biên tập.** Không cắt, không lọc, không "cho gọn". Cần bản gọn thì thêm file tóm tắt cạnh bản thô.
5. **Đóng là đóng.** `status: closed` rồi thì không sửa file nào trong thư mục đó. Đổi ý thì mở thực nghiệm mới, đặt `parent` trỏ về cái cũ.
6. **Thất bại vẫn đóng đủ.** `status: failed`, `RESULT.md` viết đủ, và thêm một mục vào `FAILURES.md` ở gốc repo: nhiệm vụ gì, đã làm gì, vì sao thất bại.
7. **Không chạm `train/` và `public_test/`.** Hai thư mục đó read-only. Mọi thứ sinh ra đi vào `experiments/<id>/out/` hoặc `artifacts/`.
8. **Tập test không bị nhìn trộm.** `train/split/test_*.jsonl` chỉ dùng để **đo**. Few-shot, tuning, chọn ngưỡng lấy từ `train/split/train_*.jsonl`. Vi phạm thì mọi số sau đó vô giá trị.
9. **In cả ba số.** Điểm, accuracy, coverage. Accuracy tăng mà điểm giảm là chuyện xảy ra thật ở bài này.
10. **Một thực nghiệm đổi một thứ.** Đổi hai thứ cùng lúc thì kết quả không gán được cho nguyên nhân nào. Cần đổi nhiều thứ thì mở chuỗi thực nghiệm nối bằng `parent`.
11. **`INDEX.md` cập nhật ngay khi mở và khi đóng**, không để cuối ngày.
12. **Đảm bảo tính tái hiện.** Đảm bảo luôn có thể tự thực thi code để tái tạo kết quả, tức là luôn có script để người dùng tự chạy agent workflow hiện có.

## Logging trong code thực nghiệm

Repo hiện chưa có logging. Code chạy thực nghiệm phải có, ở đúng ba chỗ:

| Chỗ | Log gì | Vì sao |
| --- | --- | --- |
| Gọi API model | model, prompt hash, số token, latency, kết quả parse được hay không | gọi qua mạng, không log thì không biết hỏng ở đâu |
| Reader / ingest từng file | shop, file, sheet, số dòng đọc được, số ô parse fail theo từng pattern | 49 case dữ liệu bẩn, sai im lặng |
| Mỗi câu hỏi | `id`, intent, kỳ đã resolve, nhánh đã chạy (metric / sql / abstain), số trả về | không có dòng này thì không truy được câu nào sai vì sao |

Format: JSON Lines, một dòng một event, ghi vào `logs/`. Không dùng `print`.

## Xử lý lỗi

Theo biến môi trường, như các repo khác:

- **dev** — ném lỗi ra ngay. Không nuốt, không fallback.
- **prod** — ghi log, pipeline không chết, trả kèm trường `status` để bên gọi biết là lỗi chứ không phải "không có kết quả".

Cấm: nuốt lỗi rồi trả kết quả rỗng không tín hiệu. Ở bài này nó đặc biệt độc, vì "không tìm thấy" và "lỗi" dẫn tới hai đáp án khác nhau: `0` và `unanswerable`.

## Phong cách code

Ba luật dễ vi phạm nhất khi viết code thực nghiệm:

- Không viết comment `#`. Cần comment nghĩa là tên hoặc cấu trúc đang sai.
- Mọi data/config object là Pydantic model: validated, frozen, cấm field lạ.
- `from __future__ import annotations` ở mọi file có code; type annotation đầy đủ; trả `tuple` không trả `list` ra ngoài.
