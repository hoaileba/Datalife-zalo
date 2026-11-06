# ADR 001 — Agent Claude là engine trả lời, không phải model <15B qua API

Ngày: 2026-10-29 · Trạng thái: đề xuất, chờ Hoài duyệt · Liên quan: `plan.md` §5 D5, D6, D7

## Bối cảnh

`plan.md` §6 còn trống: D5 (cách thực thi), D6 (cách model hiểu câu hỏi), D7 (số model) chưa chốt.
Yêu cầu của phiên này là **ra `submission.jsonl` cho 1000 câu public test**, không phải dựng pipeline
production. Hai việc này có ràng buộc khác nhau: pipeline production bị luật thi chặn ở model <15B,
còn việc sinh submission bây giờ thì không có ràng buộc đó.

## Quyết định

Dùng **subagent Claude làm engine**: mỗi shop một agent, agent tự viết Python để tính, không có
router/QuerySpec/SQL-fallback nào ở giữa.

Tương đương với **D5-A mở rộng** (tool library) nhưng tool được agent viết tại chỗ cho từng câu, và
**bỏ hẳn D6** (không có bước model hiểu câu hỏi thành structured spec — agent đọc câu hỏi rồi viết
code luôn).

## Đánh đổi kinh điển

Đây là **interpreter vs compiler** ở tầng kiến trúc. Pipeline trong `plan.md` là compiler: câu hỏi →
`QuerySpec` → tool → kết quả, mỗi tầng kiểm được riêng, chạy 1000 lần rẻ. Agent-as-engine là
interpreter: không có IR (intermediate representation — dạng biểu diễn trung gian) nên không có chỗ
nào kiểm chéo, bù lại không hụt 18.2% signature lạ mà §2.5 đã đo.

Giá phải trả, nói rõ:

1. **Không tái lập được bit-exact.** Chạy lại 14 agent ra kết quả khác. Luật AGENT.md 12 (tái hiện)
   chỉ đạt được ở mức "có script chạy lại agent workflow", không ở mức cùng input ra cùng output.
2. **Không đo được per-step accuracy.** Không có `QuerySpec` thì không có số router accuracy.
3. **Không phải đường đi của production.** Kết quả lần này là **chặn trên** cho pipeline <15B, không
   phải baseline của nó.

## Vì sao vẫn chọn

`plan.md` §1.4 có 3 câu chưa biết (luật thi cho mấy model, giới hạn thời gian, giới hạn lần gọi) và
D7 phụ thuộc cả ba. Dựng pipeline production trước khi biết ba câu đó là xây trên móng treo. Còn
submission thì ra được ngay.

## Thay vào đó đã không chọn gì

- **D5-B SQL only**: vẫn cần một model sinh SQL; 70.04% EX trên BIRD là chặn trên **[benchmark]**.
- **D5-C 16 tool + SQL fallback**: đúng cho production, nhưng cần O1–O8 xong trước, tức là cần chốt
  D1–D4 trước. Không ra submission trong phiên này.
