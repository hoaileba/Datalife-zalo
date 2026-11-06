Shop của bạn: `{{shop}}`.

| Thứ | Đường dẫn |
| --- | --- |
| Dữ liệu + README | `data/data/{{shop}}/` |
| Câu hỏi phải trả lời | `work/inputs/{{shop}}-questions.jsonl` — **chỉ** file này, không dùng `questions.jsonl` khác trong `data/` |
| Script (khung có sẵn, điền hàm `answer`) | `work/code/shops/{{shop}}.py` |
| Đáp án phải ghi | `work/out/answers/{{shop}}.jsonl` |
| Notes phải ghi | `work/logs/{{shop}}-notes.md` |

Shop có **{{question_count}}** câu, `as_of_date` từ {{as_of_min}} đến {{as_of_max}}.

Bắt đầu từ Bước A. Báo cáo cuối qua `finish(report)`.
