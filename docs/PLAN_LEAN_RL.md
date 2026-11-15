# Nhánh `exp/lean-rl`: student gọn (không thinking), học on-policy, rồi RL nhẹ

Ngày 14/11. Trạng thái: **plan, chưa code, chưa gọi model**. Mọi lượt gọi DeepSeek/Gemma cần người dùng cho phép
(CLAUDE.md). Số public dưới đây chỉ là số tổng hợp đã có trong `outputs/analysis/think_full_sft_gap.md`.
Plan đã qua một vòng phản biện độc lập trên code; mục 8 ghi những gì đã sửa theo phản biện.

## 0. Một câu

Giữ nguyên host và prompt (đã kiểm kỹ, không phải nút thắt). Đổi **cái student học và cách nó học**: (1) student
không thinking, học phần hiển thị của teacher mà repo **đã có sẵn** (không chạy lại teacher); (2) bù chỗ dữ liệu
thiếu đúng nhóm lỗi lớn nhất (sổ tự ghi, bảng ghi tắt, biệt danh, cách viết kỳ tắt) bằng bộ sinh tổng quát; (3) cho
student tự chạy trên pool có gold, DeepSeek viết **lượt sửa ngay tại chỗ student sai** (DAgger mức văn bản) + giữ
quỹ đạo đúng của chính student (RFT); (4) RL nhẹ (GRPO, thưởng theo điểm PA) chỉ khi có GPU và thời gian, bằng một
vòng lặp nhỏ riêng, không qua `Trainer` SFT.

## 1. Điểm xuất phát (số đã đo)

| | Số | Nguồn |
|---|---|---|
| Teacher DeepSeek flash (thinking) | PA 0.85–0.96 public; 99.3 % đúng train | DECISIONS, TRAIN_V1_ERRORS |
| Student Gemma 12B + LoRA `train_v3` (thinking bật, greedy, penalty 1.05) | PA **0.60** public 1000 (745/146/109) | gap §2 |
| Lượt student bị cắt trong thinking | 186 lượt, 88 câu không đúng; teacher 0 | gap §3 |
| **4 shop sổ tự ghi** | **125/210 câu hỏng ≈ một nửa số câu mất**; trên câu chung SFT 0.11 vs DeepSeek 1.00 | gap §3 |
| Lỗi lượt đầu / sửa thành công | student 19 % / 52 %; teacher 3–4 % / 74–100 % | gap §3 |
| `KeyError` do tên cột thuộc lòng | 41/49 | gap §4.2 |
| Mẫu sửa lỗi trong SFT | 345/8073 lượt cuối (4 %) | gap §4.3 |
| Token `train_v3` (đo 14/11) | prompt p50 13.7k; thinking p50 1.7k / p90 4.8k; phần hiển thị p50 **594** / p90 819; thinking = 78 % token có loss (nhưng prompt chiếm phần lớn token mỗi epoch: 165M) | `train_meta.jsonl` |
| Dữ liệu nothink có sẵn | `final_full`/`train_v2`: 16 287 mẫu thinking tắt, gồm reskin_1/2 (record reskin là replay, không có thinking: lý do `train_v3` bỏ chúng) | README các gói |
| Hai lần giải đồng ý | đúng 86 % khi đồng ý vs 18 % khi không (675 cặp public); train 91 % vs 49 % | DECISIONS 10/11 |

Ba nhóm lỗi lớn của student: **dữ liệu thiếu kiểu shop khó** (sổ tự ghi: nửa số câu mất), **cách học off-policy**
(không biết sửa khi chính nó sai), **thinking dài + greedy + penalty → lặp**. Host không phải nguyên nhân.

## 2. Thiết kế và lý do

### 2.1 Student không thinking (học phần hiển thị có sẵn)
- Phần hiển thị (ASKED + lập luận + nhãn + code) chỉ ~600 token và **đã chứa** gần đủ kế hoạch: `prompt.md` §2 bắt
  dòng ASKED, mọi ánh xạ nhãn, luật áp dụng. Không đổi prompt, không đổi `parse_action` (mọi chữ trước khối code đã là
  `plan`, `prompt.py:196`), dữ liệu cũ dùng lại nguyên.
- Lợi: không vòng lặp trong thinking (88 câu), sinh ít token hơn ~3 lần (rollout RL rẻ, 6 giờ dư), student nhỏ học
  CoT ngắn tốt hơn CoT dài của teacher mạnh ([2502.12143](https://arxiv.org/abs/2502.12143)); rStar2-Agent cũng
  cold-start bằng SFT không reasoning ([2508.20722](https://arxiv.org/abs/2508.20722)).
- Rủi ro: code của teacher dựa vào 1.7k token thinking student không thấy. Cách bù rẻ: `gen/sft.py --distill` (đã
  có) viết lại thinking thành lập luận hiển thị. Mẫu nào phần hiển thị quá mỏng (không có ánh xạ nhãn khi lọc trạng
  thái, không có kỳ) thì dùng bản distill hoặc bỏ: kiểm bằng regex khi lọc, không đổi định dạng.
- **Không cược một phía:** bước 0 đo cả nhánh thinking đã sửa cấu hình sinh. Chọn theo số trên val.

### 2.2 Dữ liệu bù đúng nhóm lỗi lớn nhất (bộ sinh tổng quát, không theo public)
Thêm vào `gen/` (sim → render đã có 10 họ): họ **sổ tự ghi** khó hơn (mỗi tháng một sheet, header gộp, dòng tổng
xen kẽ, cột ghi chú tự do), **sheet ký hiệu/ghi tắt** (tên hàng viết tắt trong sổ, bảng giải nghĩa riêng),
**biệt danh/tên tắt nhân viên** so với danh sách gốc, **cách viết kỳ tắt** (`T<m>/<yyyy>`, `Th <m>/<yy>`, `Q<q>`)
trong câu hỏi. Đây là các khái niệm đã ghi trong gap §4.2 là có 0 mẫu; sinh tổng quát, oracle tính gold, kiểm bằng
`scripts/check_syn.py`. Teacher DeepSeek chạy phần mới (~1.5–2k câu).

### 2.3 On-policy bước 1 (bước chính): DAgger mức văn bản + RFT
Sau SFT nothink, student chạy trên pool train (không shop/ngành val) có gold:
1. **Rollout:** mỗi câu 4 mẫu, T 0.6–1.0, seed cố định. Ghi pass-rate từng câu và **mọi lượt** (raw output).
2. **Teacher sửa tại chỗ:** ở mỗi lượt student lỗi/bị cờ, đưa đúng lịch sử của student (prompt, lượt của nó,
   observation của host) cho DeepSeek viết lượt tiếp; chạy sandbox, giữ khi ra gold. Đây đúng là trạng thái student
   hay rơi vào (19 % lỗi lượt đầu) mà SFT hiện có chỉ 4 % mẫu. Làm ở mức văn bản nên không vướng khác tokenizer.
3. **RFT** ([ReST-EM](https://arxiv.org/abs/2312.06585)): quỹ đạo đúng của chính student ở câu pass-rate ≤ 0.5,
   ưu tiên quỹ đạo lỗi rồi tự sửa đúng; tối đa 2 quỹ đạo mỗi câu.
4. SFT vòng 2 từ adapter trước: mẫu mới + ~30 % mẫu cũ, 1 epoch.

### 2.4 Abstain theo đồng thuận lúc chạy (không cần train)
k = 2–3 lần giải có seed khác nhau; nộp khi đáp án trùng, abstain khi lệch. Số đã có: đúng 86 % khi đồng ý vs 18 %
khi lệch. Với PA (sai = −1) đổi các câu lệch thành abstain là lời. Chi phí: ×k thời gian. Nothink làm k = 3 vừa 6 giờ
(think_full: 1000 câu / 66 phút có thinking). Đo trên val trước khi bật.

### 2.5 On-policy bước 2: GRPO-lite (chỉ khi có GPU, có thể sau 16/11)
- **Thưởng:** đúng +1, sai −1, abstain do model quyết định 0; **lượt hỏng (cắt, lặp, không có code/quyết định) và
  abstain do hết lượt/lặp lỗi: −0.5** (không để "viết assert cho fail" thành đường né sai rẻ nhất; `solve.py:129,147-152`).
  Không thưởng từng phần ([Arctic-Text2SQL-R1](https://arxiv.org/abs/2505.20315): thưởng mịn gây hành vi lười).
- **Lọc:** quỹ đạo có lượt hỏng ra khỏi loss nhưng vẫn tính trong trung bình nhóm
  ([SimpleTIR](https://arxiv.org/abs/2509.02479): thành phần quyết định độ ổn định). Chỉ câu pass-rate trong (0, 1).
- **Cài đặt:** một tiến trình giữ model + optimizer suốt quá trình (không dùng lại `Trainer` của `sft_lora.py`: mỗi
  lần gọi là warmup/cosine mới, bước đầu LR 0, optimizer reset, loss trung bình theo token). Mỗi vòng: rollout bằng
  `runner` qua vLLM (adapter hiện tại, bật nạp LoRA lúc chạy) → lấy **token id đúng như vLLM sinh** cho **mọi lượt
  không hỏng** (kể cả lượt đầu lỗi) → loss = Σ_token A·(−log p) / hằng số, A = r − mean(nhóm), cắt |A| ≤ 1, LR hằng,
  KL 0 → một bước → nạp adapter mới. Kiểm khi dựng: tokenize lại chat template ra đúng id đã sinh.
- **Cổng mỗi vòng:** val chạy greedy (đúng cấu hình nộp), theo dõi số câu đúng → abstain và sai → abstain; dừng khi
  đúng không tăng sau 2 lần đo. Kiểm adapter vs bản merge cho cùng đáp án trên val.
- **Kỳ vọng thật:** DataMind thấy SFT rồi RL thêm ít ([2509.25084](https://arxiv.org/abs/2509.25084)). Mỗi vòng
  512 quỹ đạo × ~1.5 lượt × 14k token prompt ≈ 10M token forward/backward, khoảng 1 giờ một bước trên 1 H100: 20–30
  vòng là 1–2 ngày. Vì vậy nó là bước cuối, không nằm trên đường 16/11.

## 3. Bảng việc (theo thứ tự, mỗi bước có cổng)

| # | Việc | Gọi model | Cổng |
|---|---|---|---|
| 0 | `train_v3` không train lại: penalty 1.0, thinking bật, T 0.6 seed 0 (chạy 2 lần: Rule 8) | Gemma val ×2 | mốc nhánh thinking |
| 0' | SFT nothink trên dữ liệu có sẵn (`final_full`/`train_v2`, thêm bản distill cho mẫu mỏng); greedy, penalty 1.0 | GPU train; Gemma val | so cặp với 0 → chọn nhánh |
| 1 | Bộ sinh mới (2.2) + test + `check_syn` | không | gold độc lập khớp oracle |
| 2 | Teacher trên phần sinh mới; gói SFT v4 = 0' + phần mới | DeepSeek ~2k câu | teacher ≥ 95 % đúng phần mới |
| 3 | SFT v4; đo val | GPU; Gemma val | hơn nhánh đã chọn ở 0/0' |
| 4 | Rollout ×4 + teacher sửa tại chỗ + RFT; SFT vòng 2 | Gemma ~3k câu ×4; DeepSeek ~1k lượt | hơn bước 3 |
| 5 | Đồng thuận k=2–3 (2.4) trên val | Gemma val ×3 | PA tăng, vừa 6 giờ |
| 6 | (tuỳ GPU) GRPO-lite | Gemma 64×8 mỗi vòng | 2.5 |
| 7 | Val 2 lần, merge, Docker | Gemma | lệch ≤ 0.01 PA |

Bước 1 làm ngay (thuần code), song song với 0 và 0'.

## 4. Đo (không dùng public để chọn)
- **Val:** `biz_108/110/130` (277 câu, rulebook chuẩn, shop thật) + `data_gen/syn_v2/val` (519 câu, ngành mới,
  rulebook viết lại) + val của họ mới ở 2.2 (giữ riêng vài shop). Không train các shop/ngành này ở mọi bước.
- So **cặp câu** giữa hai checkpoint; báo đúng/sai/abstain, PA, lỗi lượt đầu, tỉ lệ sửa thành công, lượt cắt.
- Public chỉ đo ở cuối, khi người dùng cho phép.

## 5. Chi phí ước lượng
- DeepSeek ~0.0016 USD/câu: bước 2 ≈ 3–4 USD; bước 4 ≈ 2 USD. Không chạy lại teacher toàn pool.
- Gemma: val 800 câu mỗi lần đo; bước 4 ~12k quỹ đạo; cần vLLM riêng (gateway chỉ 2 luồng).
- SFT nothink: token có loss giảm ~4.6 lần nhưng token prompt không đổi, nên thời gian train chỉ giảm ít.

## 6. Cố ý KHÔNG làm
- Không đổi prompt/định dạng trả lời (khối kế hoạch cố định từng nghĩ tới: làm lệch mọi record cũ và adapter hiện
  có, phải chạy lại teacher 6–8k câu, trong khi phần hiển thị đã gần đủ).
- Không đổi host, không rút cookbook, không decompose/metric layer (đã thử 10/11).
- Không thưởng từng phần; không on-policy distillation theo logit (khác tokenizer); không framework RL lớn.

## 7. Câu hỏi cho người dùng
1. **Hạn Docker 16/11 còn đúng không?** Nếu đúng: đường thực tế là 0, 0', 1–3, 5; bước 4 nếu kịp; 6 sau hạn.
2. **GPU train/rollout:** máy nào, mấy giờ? (máy này 1×3090 24 GB, không đủ 12B ở 16k token). Lần train `train_v3`:
   rank, epoch, loss val?
3. Adapter nothink từ `train_v2`/`final_full` đã từng được train/đo chưa? Có thì 0' xong ngay.

## 8. Đã sửa sau phản biện (14/11)
- Bỏ khối kế hoạch cố định và lượt chạy lại teacher (A/B): dùng dữ liệu nothink có sẵn + `--distill`.
- Thêm nhóm lỗi lớn nhất (sổ tự ghi, ghi tắt, biệt danh, kỳ tắt) vào dữ liệu.
- GRPO-lite không qua `sft_lora.py` (warmup → LR 0 ở bước đầu, optimizer reset, chuẩn hoá theo độ dài, completion bị
  chuẩn hoá lại không phải token đã sinh, chỉ giữ lượt cuối); thưởng −0.5 cho lượt hỏng/hết lượt; ra khỏi đường 16/11.
- Mốc bước 0 công bằng: so với adapter train nothink, không phải `train_v3` tắt thinking; bỏ lập luận "greedy tất định
  hơn sampling có seed" (cả hai cùng nhiễu batch, kiểm bằng 2 lần chạy).
- Thêm abstain theo đồng thuận lúc chạy (số đã có: 86 % vs 18 %).
