# ADR 011: Phân tích câu hỏi bằng LLM, câu gốc vẫn là nguồn sự thật

Trạng thái: Hoài yêu cầu làm ngày 2026-11-07 (hướng B), chờ duyệt chi tiết

## Bối cảnh

Câu hỏi có từ lóng, từ địa phương, viết tắt (thống kê trên 4000 câu: `experiments/EXP-20261107-02-question-rewrite/out/dialect_stats.md`). Regex `question_norm.normalize` không phủ được từ mới và không hiểu nghĩa. EXP-20261107-02 cho thấy LLM viết lại hay đổi nghĩa cách ghi ngày tháng ngắn ("5/25" thành "Ngày 5/25").

## Quyết định

1. Một lời gọi LLM mỗi câu (`datamate_agent/question_rewrite.py`) trả 4 dòng: câu viết lại, dạng đáp án, số phần tử, thông tin cần. Kết quả cache theo id câu.
2. Câu viết lại chỉ hiện cho model đọc. Tìm ví dụ, tên, kỳ hỏi, thanh toán vẫn lấy từ câu gốc. (Sửa ngày 2026-11-07: ban đầu tìm ví dụ bằng câu viết lại, đo trên 1000 câu public thì ở các câu đổi ví dụ top-1 được 6 mất 18; tìm bằng câu gốc thì PA 0,846 lên 0,856.)
3. Code kiểm câu viết lại: số giữ nguyên (theo giá trị), kỳ đọc ra giữ nguyên, không thêm từ chỉ thời gian (ngày, tuần, thứ, năm, quý) mà câu gốc không có, không bỏ đơn vị, tên đã nối còn nguyên. Sai thì bỏ cả câu viết lại lẫn phân tích.
4. Trường "thông tin cần" ghi vào cache nhưng không đưa vào prompt: trên 100 câu nó lẫn cả thời gian và số đo ("tháng 8/2025", "số lượng đơn hàng").

## Pattern và đánh đổi

Query rewriting (Ma et al., 2023, EMNLP) theo kiểu generate-and-verify: LLM đề xuất, code kiểm bất biến. Đánh đổi: thêm một lời gọi API mỗi câu và một điểm hỏng; câu bị loại quay về hành vi cũ.

## Phương án đã loại

- Câu viết lại thay câu gốc ở mọi chỗ: LLM có thể "chữa" câu không trả lời được thành câu trả lời được.
- Danh sách cụm từ giữ nguyên rút từ lỗi public (ngon, thân thiện, khách nữ): overfit public.

## Đo sau khi áp dụng

EXP-20261107-03: public 1000 câu PA +0,856 (bộ cũ +0,849). Câu viết lại hợp lệ 895/1000.
