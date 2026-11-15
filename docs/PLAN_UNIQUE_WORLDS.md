# Unique worlds: mỗi câu một bài toán độc nhất

## Vì sao
Dữ liệu SFT cũ (30 shop train, reskin, syn_v2) có cấu trúc lặp lại:
- một rulebook cho cả split;
- tên file mang nghĩa và lặp giữa các shop;
- khoảng 20 ngành viết tay;
- README theo khuôn.

Student học thuộc "thế giới train" thay vì học đọc rulebook, README và schema. Vì vậy cùng dữ liệu, ds-fl làm được
nhưng Gemma sau SFT lại không làm được trên shop lạ.

Ở luồng mới, mỗi sample (một câu hỏi) có rulebook, README, bảng và ngành của riêng nó. Mọi sample train là trajectory
do ds-fl giải, lọc theo gold oracle.

## Nguyên tắc
1. **Nghĩa do code sinh, bề mặt do model sinh và có kiểm.**
   - Luật, dữ liệu, đáp án đến từ `gen.oracle` (`Rules`), nên gold đúng tuyệt đối.
   - Model chỉ viết ngành, lời văn luật (ngân hàng diễn đạt lại đã kiểm) và README (kiểm từng tên, số, ngày).
2. **Mỗi thế giới dựng lại được từ seed của nó.** `manifest.jsonl` giữ mã băm rulebook, bộ file + README và câu hỏi.
   Thế giới nào trùng một trong ba mã thì bị bỏ.
3. **Dùng lại pipeline có sẵn:** `sim`, `render`, `reskin` (đổi tên + kiểm bằng `load_business`), `rulebook_gen`,
   `questions`, `surface`, `oracle`, `teacher`, `package`.

## Thành phần
| Bước | Code | Gọi model |
|---|---|---|
| Ngành | `gen/industry_gen.py` → `gen/assets/industries_gen.json` (registry `gen/industries.py`) | có, một lần, khoảng 300 ngành |
| Ngân hàng lời luật | `gen/rule_bank.py` → `gen/assets/rule_bank.json` | có, một lần, khoảng 145 dòng × 4 cách viết |
| Rulebook một thế giới | `gen/world_rules.py` (`compose_world`) | không |
| Thế giới | `gen/world.py` | chỉ khi bật `--llm-readme` |
| Teacher | `gen/teacher.py --split <thư mục thế giới>` (nhiều split mini; `--redo-from` cho lượt hai) | có |
| Đóng gói SFT | `gen/sft.py`, `gen/package.py`, `gen/validate.py` (định dạng v5) | không |

### Ngành
- Code rút **traits** cho từng ngành: lô hạn dùng, dòng dịch vụ, size (chữ hoặc ngoặc), hàng cân ký, món kèm,
  bàn / biển số xe, mùa riêng. Kèm theo là một gợi ý lĩnh vực trong 50 lĩnh vực.
- ds-fl sinh phần còn lại của ngành.
- Code kiểm trước khi nhận:
  - đủ số món mà traits đòi;
  - giá, đơn vị, quy đổi hợp lệ; tên không trùng;
  - không trùng ngành đã có.
- Traits quyết định section luật (`industries.sections`), nên ngành mới tự có câu hỏi riêng
  (`questions.allowed`) và luật riêng (`world_rules.TEMPLATES`), không cần code theo từng ngành.
- Khoảng 10% số ngành được đánh dấu `val` và không vào train.

### Rulebook
- **Nghĩa:**
  - `rulebook_gen.compose` rút 0–3 luật mặc định bị đổi (`STACKABLE`) và bỏ section của ngành train vắng mặt;
  - thêm section của ngành, dựng từ khuôn có tham số (tên ngành, size, nhóm món kèm, ngày của mùa);
  - một số dòng có phương án khác (nghĩa khác, `Rules` khác); mùa có thể lệch ±10–15 ngày.
- **Lời:**
  - mỗi dòng có trong ngân hàng được thay bằng một cách viết đã kiểm, xác suất 0.7;
  - dòng trong một bảng được xáo thứ tự (mục giữ số, nên tham chiếu §N vẫn đúng);
  - bố cục rút ngẫu nhiên: bảng, gạch đầu dòng, hoặc đánh số 1.1, 1.2; tiêu đề cũng đổi.
- **Ngân hàng lời luật** (sinh một lần). Mỗi cách viết phải qua cả hai lớp kiểm:
  - kiểm máy: cùng số ô, số, `code`, §, chỗ giữ chỗ, số chữ "không";
  - một lượt gọi riêng chấm xem hai câu có cùng một luật không.

### File và README
- **Kiểu tên:**
  - 50% tên **mờ**: `t_8kq2.xlsx`, `export_20250612c.csv`, sheet `Sheet3`, bảng SQLite `tbl_a7b`;
  - 30% tên có nghĩa (từ đồng nghĩa của `reskin`);
  - 20% trộn hai kiểu.

  Header cột đổi theo từ đồng nghĩa. Nhãn trạng thái giữ nguyên như khi render (đáp án không đổi). Bản đổi tên được
  đọc lại bằng `load_business` và so từng bảng; đổi tên nào làm reader đọc khác thì được hoàn lại.
- **README:**
  - bản render được đổi sang tên mới, độ chi tiết rút ngẫu nhiên (full / partial / brief);
  - với tên mờ, mỗi file có một dòng nói nội dung, trừ ở mức brief (khi đó agent phải tự suy ra từ cột);
  - với `--llm-readme`, 70% thế giới có README do ds-fl viết lại theo một giọng rút ngẫu nhiên. Bản viết lại chỉ được
    giữ khi còn đủ mọi tên trong backtick / chữ đậm, mọi số, ngày cuối dữ liệu, và không lộ tên cũ.

### Câu hỏi
- Mỗi thế giới một câu, từ `questions.sample`.
- Trọng số intent lấy mũ 0.6 để intent hiếm xuất hiện nhiều hơn, cộng thêm phần tăng cho luật vừa bị đổi
  (`rulebook_gen.focus`).
- `moved` = luật riêng của thế giới làm đáp án khác với luật mặc định.

## Teacher hai lượt
```
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
$PY -m gen.teacher --split data_gen/uniq --out outputs/teacher/uniq_nt --config config.deepseek_direct_nothink.yaml \
    --all --price 0.28,0.028,0.42 --max-usd 5 --yes
$PY -m gen.teacher --split data_gen/uniq --out outputs/teacher/uniq_th --config config.deepseek_direct.yaml \
    --redo-from outputs/teacher/uniq_nt --price 0.28,0.028,0.42 --max-usd 5 --yes
$PY -m gen.package --teacher outputs/teacher/uniq_nt --teacher outputs/teacher/uniq_th --out <package>
```
- Chỉ trajectory đúng theo gold mới thành sample.
- Lượt không phải lượt cuối chỉ được giữ khi đó là một lượt look đã chạy, hoặc một đáp án bị cờ mà lượt sau xác nhận
  không đổi (`gen.sft.imitable`). Lượt lỗi chỉ nằm trong lịch sử.
- Thinking của teacher được lưu trong `meta.thinking`.

## Chi phí (DeepSeek flash: $0.28 / $0.028 / $0.42 cho mỗi 1M token)
Các câu không còn chung cache: system prompt khoảng 7k token vẫn hit cache, còn rulebook và shop khoảng 8–9k token là miss.

| Hạng mục | Chi phí |
|---|---|
| Mỗi câu, chạy hai lượt | khoảng $0.004–0.005 |
| 3000 câu | khoảng $13–16 |
| Ngành (300) | khoảng $0.5 |
| Ngân hàng lời luật | khoảng $0.1 |
| README do model viết | khoảng $0.001 mỗi thế giới |

Dựng thế giới mất khoảng 30 giây mỗi job; 8 job cho khoảng 4 giây mỗi thế giới.

## Sau rà soát (14/11): bám sát dữ liệu thật
Một agent đã so prompt thực tế của pilot với train và public (chỉ so cấu trúc và thống kê). Prompt, câu hỏi và ngành
đã gần với thật. Ba chỗ còn xa (rulebook, tên file, README) đã sửa như sau:

**Rulebook**
- 75% thế giới theo kiểu `train`: lời và bố cục bảng của train; khác biệt chỉ đến từ luật bị đổi, dòng thêm và section ngành.
- 25% thế giới theo kiểu `heavy`: diễn đạt lại theo ngân hàng, xáo dòng, bố cục bảng / gạch đầu dòng / đánh số.
- §6 có thêm 2–5 section của ngành khác làm nhiễu. Chỉ ngày của mùa trong các section này đi vào `Rules` (mỗi mùa có
  khoá theo ngành của nó), nên gold không đổi.
- Tiêu đề nêu tên bộ, không nêu tên ngành.
- Một hàng size có hơn 5 cỡ thì viết dạng chung, không liệt kê từng cỡ.
- Cách viết lại luôn giữ dấu gạch đầu dòng của dòng gốc.

**Tên file**
- 10% thế giới dùng tên mờ, 90% dùng tên có nghĩa (từ đồng nghĩa của reskin).
- Bảng SQLite luôn giữ tên có nghĩa.
- Dòng mô tả file chỉ xuất hiện ở thế giới tên mờ, mỗi file với xác suất 0.5. Sheet theo kỳ không được liệt kê.
- Tên dạng `export_YYYYMMDD` lấy ngày sau ngày cuối của dữ liệu.

**README**
- Mức chi tiết rút một lần duy nhất: full 0.6 / partial 0.27 / brief 0.13.
- Tiêu đề mục theo dạng của train: `## Cột trong \`F\`, sheet \`S\``.
- README do model viết phải giữ khuôn (giữ heading và câu "Dữ liệu có đến hết ..."), không có lời chào hay giọng thư.

**Bố cục file mới** (`gen/world_layout.py`; dữ liệu được đọc lại để kiểm, không khớp thì giữ bản gốc)
- Mỗi tháng một file: xác suất 0.35 khi có workbook sheet theo tháng.
- Workbook gộp các danh mục: xác suất 0.3.

**Khác**
- id dạng `biz_<số>`; thế giới val nằm ở dải số riêng.
- Câu hỏi không còn lặp đơn vị khi tên hàng bắt đầu bằng chính đơn vị đó.
- Mặt hàng kiểu giao hàng, phí, voucher, đặt cọc bị cấm khi sinh ngành.

**Pilot 2** (30 thế giới, seed 2): teacher tắt thinking đúng 26/30; lượt thinking cho 4 câu còn lại đúng 1. Tổng 27/30
(0.90), $0.175. Cả 3 câu còn sai đều là model sai, gold đúng: bỏ sót đơn COD khi tính công nợ; tồn kho tại ngày quá
khứ (bỏ nguyên đơn có trả hàng); tự suy ra nhóm hàng từ tên hàng. Gói SFT có 30 mẫu, kiểm tra qua.
