# STEPS

## 2026-11-06T11:00 — bước 1/5: đọc code nhận diện
`question_hints` (fewshot.py) khớp tên sau khi bỏ dấu: "trả"→nhóm `trà`, "rứa"→`rửa`, "trung bình"→`bình`. `period_of` thiếu tháng/quý không ghi năm, `q1/2026`, khoảng tháng, cùng kỳ tháng trước, trước Tết.

## 2026-11-06T11:10 — bước 2/5: dò 24 câu F, E (`scratchpad/probe24.py`)
Helper đúng khi gọi đúng: price_effect(price=) −3.6, −50.0; new_machine_share 77.26, 78.49; trade_in_order_share 4.6; installment_overdue 20000000; quarter 842; between 200; same_days −4.82, −5.38; tháng không ghi năm năm 2026 khớp 4 câu.
Lỗi helper thật: Tiffy Dey −14.53/−19.6 (ref −33.51/−5.4): ô hệ số `25 vỉ` mất đơn vị khi chuẩn hoá, `lines` chỉ một đơn vị lớn mỗi hàng. repair_count `sửa điện` 6 (ref 25), `thay dầu láp` 0 (ref 26). machines_sold(kind='cũ') 0 (ref 59).

## 2026-11-06T11:25 — mốc oracle trước khi sửa
train 2187/3000, public 567/1000 (logs/01-*).

## 2026-11-06T11:40 — bước 3/5: sửa
- normalize: cột `factor_unit` giữ đơn vị ghi kèm hệ số; shop `_chained_factors` nhân hệ số qua đơn vị trung gian, đủ mọi đơn vị lớn của một hàng.
- repair `job_pattern` theo rulebook dòng 116; phone `machine_kind`; FILTER_SYNONYMS thêm `tien tuoi`, `tm`, `xi o di`, `ship cod`.
- intents: khoảng tháng, `q1/2026`, quý/tháng không ghi năm theo as_of (rulebook dòng 35), cùng kỳ tháng trước, `baseline_of`.
- fewshot: `linked_match` kiểm dấu, hint thanh toán theo thứ tự câu, hint kỳ đem ra so; agent truyền as_of.
Kiểm: Tiffy −33.51, −5.4; top 5 dev_005 khớp; sửa điện 25; dầu láp 26; máy cũ 59; trước Tết 46.33. Chuẩn hoá lại dev_005: chỉ catalog_danhsachquydoi khác (thêm cột).

## 2026-11-06T11:55 — bước 4/5: oracle sau khi sửa
train 2201/3000 (+14, 0 thành sai), public 570/1000 (+3, 0 thành sai) (logs/03-*).

## 2026-11-06T11:56 — bước 5/5: chọn câu chạy lại
Shop đổi lines: biz_102, biz_103, biz_121, biz_122, dev_005. Public: prompt đổi 63, shop đổi 87, gộp 148. Test: prompt đổi 14, shop đổi 75, gộp 83 (out/rerun_*.jsonl). Chạy agent 5 luồng, public trước, test sau (logs/04-agent.cmd).

## 2026-11-06T12:45 — chạy lần 1 xong, lỗi mạng
Public 59/148 có đáp án, 89 câu `APIConnectionError`; test 0/83 có đáp án, 83 câu cùng lỗi. Kết nối kiểm lại: HTTP 200. Chạy lại riêng các câu lỗi (out/retry_*.jsonl).

## 2026-11-06T13:45 — chấm và đóng
Public PA 0.845 (922/77/1), test +290 (368/78/4). File nộp out/submission.jsonl: 1000 dòng, 0 id trùng, unanswerable đúng format. Đóng.
