# ADR 003 — Abstain policy vòng 1: ba tín hiệu nhị phân, không ước lượng p

Ngày: 2026-10-29 · Trạng thái: đề xuất, chờ Hoài duyệt · Liên quan: `plan.md` §5 D9, D10, D11

## Bối cảnh

Hàm mất mát: đúng +1, sai −1, bỏ trống 0. EV một câu có xác suất đúng `p` là `2p − 1`, nên **trả lời
chỉ có lợi khi `p > 0.5`** (`plan.md` §1.1).

Không có đáp án cho public test, nên **không đo được `p`** trên tập này. D9-B (ngưỡng per bucket) cần
`p` theo bucket, mà `p` đó phải đo trên train split — chưa đo.

## Quyết định

Vòng 1: **D10-B**, ngưỡng cố định trên tín hiệu nhị phân. Agent bỏ trống (`{"type": "abstain"}`)
khi gặp **một trong ba** tín hiệu:

| # | Tín hiệu | Ví dụ |
| --- | --- | --- |
| 1 | Không xác định được cột nào mang thông tin câu hỏi cần, sau khi đã đọc README | câu hỏi nhóm khách mà shop không có cột nhóm khách và README không nói cách suy |
| 2 | Tính được nhưng hai cách đọc luật ra hai số khác nhau, không chọn được bằng rulebook | "doanh thu" khi shop có cả `Thành tiền` dòng hàng và `Tổng đơn` sau giảm, không rõ cột nào đã trừ giảm giá dòng |
| 3 | Kết quả không qua được sanity check của chính agent | doanh thu một tháng lệch >50% so với các tháng kề mà không có lý do đọc được từ dữ liệu |

**`unanswerable` không phải van an toàn.** Nó là một đáp án có điểm: đúng +1, sai −1. Chỉ nộp
`unanswerable` khi khớp đúng một trong hai nguyên nhân **deterministic** của rulebook §7:

- kỳ hỏi nằm **hoàn toàn** ngoài khoảng ngày có dữ liệu của shop (so với mốc `Dữ liệu có đến hết
  DD/MM/YYYY` trong README **và** khoảng ngày thật đo được từ file);
- shop **không ghi** loại thông tin câu hỏi cần (không có file, không có cột).

Không chắc thuộc hai nguyên nhân đó → **abstain**, không phải `unanswerable`.

## Đánh đổi kinh điển

Đây là **precision-recall tradeoff** đặt vào hàm mất mát không đối xứng. Khác với abstain thông
thường, ở đây **bỏ trống là lựa chọn trung tính thật** (0 điểm), nên ngưỡng tối ưu không phải
"chắc chắn" mà đúng bằng `p = 0.5`.

Hệ quả khó chịu: ba tín hiệu trên là **nhị phân**, không phải `p`. Chúng bắt được vùng `p` rất thấp
(không có cột thì `p ≈ 0`) nhưng **không phân biệt được `p = 0.45` với `p = 0.7`** — đúng chỗ mà
D9-B ra đời để xử lý. Vòng 1 bỏ trống phần đó, tức là **đang trả lời cả những câu `p` quanh 0.5**.

`plan.md` §1.1 đã đo cái giá: một hệ thống accuracy 60% trả hết 1000 câu được 200 điểm, còn
accuracy 80% trả 500 câu được 300 điểm.

## Việc đo còn treo, phải làm trước vòng 2

1. Chạy đúng recipe này trên `train/split/train_questions.jsonl` (**không** chạm `test_*.jsonl`,
   AGENT.md luật 8) → có `p` thật, theo bucket độ phức tạp của D9-B.
2. Có `p` rồi mới chọn được ngưỡng per bucket. Trước đó mọi ngưỡng số đều là bịa.

## Thay vào đó đã không chọn gì

- **D10-A trả hết**: mỗi câu `p < 0.5` là âm điểm, và §2.9 đã xác nhận 51 case dữ liệu bẩn làm
  "số vẫn ra, chỉ là sai".
- **D10-C self-consistency**: đúng về nguyên lý (ước lượng `p` thật) nhưng cần chạy mỗi shop k lần;
  chưa làm vòng 1.
