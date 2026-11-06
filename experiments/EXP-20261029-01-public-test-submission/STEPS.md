# Nhat ky EXP-20261029-01-public-test-submission

Append-only.

## 2026-10-29T12:05 — bước 1-3/7
Đã làm:    mở thực nghiệm, 3 ADR, toolkit datamate (norm/periods/calendar_vn/fmt/tabio), 41 test
Kết quả:   41/41 pass. Tết 2026 khớp lịch thật. Phát hiện bẫy dòng "Cộng ngày" ở dev_001 làm lệch 2x doanh thu
Bước tiếp: bước 4-5 — calibration agent trên biz_112 + 14 shop agent song song

## 2026-10-29T12:30 — bước 4-6/7
Đã làm:    spawn 15 agent (1 calibration biz_112 có đáp án + 14 shop agent). Viết code/merge.py + code/score.py + code/run.sh
Kết quả:   merge.py dry run: 1000/1000 id khớp questions.jsonl, hiện 1000 abstain (agent chưa nộp) -> đã có submission an toàn 0 điểm làm sàn
Bước tiếp: chờ 15 agent, chấm calibration, merge lần cuối, viết RESULT.md

## 2026-10-29T15:30 — vòng 1 chết, mở vòng 2 theo batch
Đã làm:    15 agent vòng 1 chết hết vì session rate limit (429, reset 14:50). Vớt được dev_002/009/011. Sửa 3 bug toolkit do agent chết báo về
Kết quả:   49/49 test pass (thêm 8 test regression). parse_money(19tr990)=19990000, is_blank(Nan)=False, fold_key khớp tên không dấu. 3 script vớt chạy lại ra đáp án KHÔNG ĐỔI -> 102/1000 câu đã có
           Dấu hiệu brief cho dev_008 SAI: shop đó có cột trạng thái TT đơn. Đã thêm mục 3c vào brief: dữ liệu thắng dấu hiệu
Bước tiếp: batch 1 = dev_003 + dev_006 + dev_008 (339 câu, ba shop nặng nhất)

## 2026-10-29T15:55 — batch 1, 2/3 shop xong
Đã làm:    dev_006 (111 câu) + dev_008 (99 câu) nộp xong. Tôi chạy lại script của cả hai, diff file đáp án -> y hệt (tái lập OK)
Kết quả:   coverage 440/1000. dev_006 tự kiểm 10 câu hai đường 10/10 khớp; dev_008 tự kiểm 6 câu 6/6 khớp
           Bẫy dòng trùng khít xác nhận ở 3 shop: dev_006 1350, dev_008 1347 cặp, dev_007 2762. Bẫy dòng tổng cộng ở 3 shop: dev_001 554, dev_008 587, dev_004 18+27
           -> đã thêm mục 3d (hai lớp dòng rác bắt buộc kiểm) và 3e (mã hay tên) vào brief
Bước tiếp: chờ dev_003 đóng notes, rồi batch 2 = dev_004 + dev_005 + dev_001

## 2026-10-29T16:05 — batch 1 đóng, batch 2 chạy
Đã làm:    dev_003 nộp xong, chạy lại script -> file đáp án y hệt. merge.py. Launch batch 2 = dev_004 + dev_005 + dev_001
Kết quả:   batch 1 xong cả 3 shop (dev_003 129 + dev_006 111 + dev_008 99 = 339 câu). Coverage 440/1000 (44%)
           Cả 3 shop tái lập được. Tự kiểm đường thứ hai: dev_003 20/20 khớp, dev_006 10/10, dev_008 6/6
           Token subagent batch 1: 220k + 214k + 241k = 676k
           Bẫy mới dev_003: khoá nối lẫn khoảng trắng (12.371 phiếu thu mồ côi nếu không squeeze); 69 cách viết tên cho 50 mặt hàng
Bước tiếp: hết batch 2 thì DỪNG, chờ lệnh Hoài (ước lượng ~80% cửa sổ limit)

## 2026-10-29T16:20 — DỪNG theo lệnh Hoài
Đã làm:    stop 3 agent batch 2 (dev_004, dev_005, dev_001). Vớt file trên đĩa, merge
Kết quả:   vớt được dev_001 (87, script có WALKIN_KEYS gồm "kl", chạy lại ra file y hệt) và dev_005 (87, có notes, agent chết giữa bước D; chạy lại bị SIGKILL exit 137 nên CHƯA kiểm tái lập). dev_004 không có gì
Bước tiếp: chờ lệnh. Còn lại: dev_004, dev_007, dev_010, dev_012, dev_013, dev_014 + calibration biz_112 + verify dev_002/005/009/011

## 2026-10-30 — mở lại, batch 3
Đã làm:    thêm lớp 4 (khách vãng lai viết kiểu kl) vào brief. Launch batch 3 = dev_004 + dev_014 + dev_007
Kết quả:   trạng thái mở: 614/1000
Bước tiếp: batch 3, rồi batch 4, rồi DỪNG

## 2026-10-30 — batch 3 đóng
Đã làm:    dev_007, dev_014, dev_004 nộp xong. Chạy lại cả 3 script -> file y hệt. Lưu verify.py của dev_004 từ scratchpad vào code/shops/dev_004_verify.py. Kiểm 3 câu unanswerable nhóm hàng của dev_004: không file nào có cột nhóm (peek cả 7 file); train split có 1 câu cùng mẫu (biz_106, nhóm khách) đáp án unanswerable
Kết quả:   coverage 832/1000. Token batch 3: 163k + 167k + 188k = 518k. Bẫy kl xác nhận ở 4 shop (dev_001/004/007/014)
Bước tiếp: batch 4 = dev_010 + dev_013 + dev_012, rồi DỪNG

## 2026-10-30 — batch 4 đóng, DỪNG
Đã làm:    dev_012, dev_010, dev_013 nộp xong; chạy lại cả 3 script -> file y hệt. Lưu verify.py của dev_013. Đo train split các câu tính từ chủ quan
Kết quả:   1000/1000 có dòng, 996 có đáp án, 4 abstain. Token batch 4: 155k + 161k + 172k = 488k
           Train split: 4/4 câu tính từ chủ quan (khen, tận tâm, chu đáo, quý mến) là unanswerable. Public test có 8 câu cùng loại, đang xử theo 3 cách -> đề xuất đổi 6 câu, CHỜ Hoài quyết (đi ngược ADR 003)
           Lỗ hổng toolkit: drop_subtotal_rows không bắt dòng tổng ghi chữ trong cột khoá (dev_010)
Bước tiếp: chờ lệnh. Còn: quyết đề xuất tính từ chủ quan; batch 5 = calibration biz_112 + kiểm lại dev_002/005/009/011


## 2026-10-30 — Hoài: điểm public 0.99; bỏ abstain, dò câu rủi ro cao

Đã làm:    đổi 4 abstain -> unanswerable trong script dev_003/007/010/012 (bỏ luôn ABSTAIN set của dev_012), chạy lại 4 script, merge.
           Quét rủi ro: từ khoá chủ quan, đáp án <=0, phân bố dấu %, đọc mục "quyết định đọc luật" của notes,
           đo dòng trùng thô ở dev_002/009/011, rà 28 câu unanswerable.
Kết quả:   submission 1000 dòng, 0 abstain, 28 unanswerable. Mỗi script chỉ đổi đúng 1 dòng (bản cũ ở scratchpad/before).
           Dấu % so sánh kỳ: có cả âm lẫn dương -> không có lỗi đảo dấu hệ thống.
           dev_002: dòng trùng thô = header lặp (đã lọc). dev_009: script dedupe bằng tuple, 22.490 mã HĐ duy nhất.
           dev_011: 0 đơn có hai dòng giống hệt (trùng thô là dòng tiếp nối của hai đơn khác nhau, rulebook dòng 145: tính cả hai).
           Rủi ro cao: 3 câu ĐÃ trả lời nhưng dùng từ gần nghĩa với term rulebook định nghĩa mà KHÔNG phải term đó:
           dev_003 q_6e929cf36203 "trung thực" (rulebook chỉ có "trung thành"), dev_006 q_611bf24dd2f9 "uy tín",
           dev_013 q_6830bf77b8c5 "đáng tin cậy" (rulebook chỉ có "nhà cung cấp chính").
Bước tiếp: chờ Hoài quyết có đổi 3 câu này không, và cách nộp để tách được hiệu ứng.

## 2026-10-31 — điểm public 0.99400 sau khi đổi 4 abstain → unanswerable
Đã làm:    Hoài nộp submission.jsonl (0 abstain, 28 unanswerable) được 0.99400 (trước đó 0.99 với 4 abstain)
Kết quả:   theo luật +1/−1/0 chia 1000: trước c+w=996, c−w=990 → sai 3; nay c+w=1000, c−w=994 → sai 3.
           Điểm tăng đúng +0.004 = 4 câu đổi đều ĐÚNG (dev_003 "vì gọi nhầm món", dev_007 "ngon nhất",
           dev_010 "thân thiện nhất", dev_012 "nhiệt tình nhất" đều là unanswerable) → mẫu tính từ không định nghĩa
           đúng 4/4 trên public, cộng 4/4 ở train.
           Ghi out/submission-candidate-3-subjective.jsonl: đổi thêm 3 câu cùng mẫu (q_6e929cf36203, q_611bf24dd2f9,
           q_6830bf77b8c5) sang unanswerable. Chưa thay submission.jsonl
Bước tiếp: Hoài quyết có nộp bản candidate không. Dự đoán: đúng cả 3 → 1.00000; sai cả 3 → 0.98800
