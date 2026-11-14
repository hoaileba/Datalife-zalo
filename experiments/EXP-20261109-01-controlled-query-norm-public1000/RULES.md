# Controlled query normalization — luật lần chạy

## Thay đổi duy nhất được thử

Thay preprocessing contract: thay câu viết lại tự do bằng các edit source/replacement có kiểm soát, vẫn trả metadata shape/count/needs trong cùng response JSON và giữ chính sách của agent đối với các trường đó. Không tuyên bố lần này cô lập riêng hiệu quả edit khỏi việc model sinh lại metadata.

User đã yêu cầu trực tiếp thử LLM normalization và chạy đủ 1000 public. Điểm so với parent là đối chiếu với cached run cũ, không phải paired control được chạy lại cùng thời điểm.

## Luật được code hoá

| Điều cần bảo vệ | Vị trí |
| --- | --- |
| Chữ số, kỳ, tên, đơn vị trong câu phải còn nguyên | `question_normalize.apply_edits`, kiểm bổ sung `check_rewrite` hiện có |
| Source của edit phải có thật và duy nhất, không cắt từ, không chồng edit | `question_normalize.apply_edits` |
| Tên đã nối và ID có dạng chữ-số được giữ | `protected_spans` |
| Không thêm/bớt/đổi marker số đo, phủ định, phép so sánh đã nhận biết | tuple marker theo vị trí, giữ số lần và thứ tự |
| Edit bị từ chối không được âm thầm dùng; agent dùng câu gốc | cache Rewrite ghi original và problem rõ |
| Giữ seed, model alias, prompt v10, thư viện, helper, bảng norm và rerank | source/input snapshot và runner |

## Cố ý chưa làm

- Không sửa ví dụ curated sai `dia → ly`, không sửa fuzzy matching, gate unanswerable, helper hoặc giới hạn generation của agent. Đó là biến thể khác.
- Không bổ sung lời giải theo ID hoặc theo shop; chín ID số đơn chỉ dùng phân tích sau khi chấm.
- Không đọc `train/split/test_*`, không nộp lên leaderboard và không sửa gold Claude.
- Không tự promote mode normalize thành default trước kết quả.
- Không rebuild normalization dữ liệu shop; dùng bản sao các bảng norm mà run parent đang dùng trong workspace.

## Giới hạn của validator

Validator không chứng minh mọi edit cùng nghĩa. Các marker chỉ bao phủ một số dấu hiệu tường minh, tên chưa nối được có thể chưa được bảo vệ. Metadata shape/count/needs vẫn do model suy luận. Rule ngoài marker có thể bị đổi nghĩa dù edit qua kiểm. Các marker bảo thủ có thể từ chối một normalization có ích. Các quyết định này là giả thuyết lần thử, chưa phải tuyên bố bảo đảm semantic.

`docs/02-plan-kien-truc.md` không có trong checkout. Mục tiêu hoàn tất lần này là 1000 câu đi qua variant, tạo submission đủ ID, báo score/accuracy/coverage và gained/lost; không tự bịa milestone kiến trúc cũ.

## Tái hiện và logging

Chạy từ `code/src` snapshot, copy toàn bộ prompt JSONL, freeze baseline/reference/questions/norm và hash. Runner ghi raw request/reply, prompt hash, latency, token usage khi server có trả, và unavailable khi không có. ContextVar gắn ID từ question object cho normalize/rerank/solve, không suy ID từ câu chữ có thể trùng. Không lưu endpoint/key vào file.

Smoke dùng ba câu synthetic và một câu public không chấm gold; full chạy lại đủ 1000 từ đầu, không ghép câu smoke. Không tune prompt sau khi xem score public smoke. Các log test thất bại giữ nguyên.
