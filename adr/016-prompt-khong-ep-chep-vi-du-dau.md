# ADR 016: Prompt không ép chép ví dụ đầu (v11)

Trạng thái: bỏ (Hoài quyết 2026-11-07), quay về lời dặn v10; giữ ADR 014 và 015

## Bối cảnh

v10 dặn "chép đúng dạng code của ví dụ", gợi ý ghi "câu đầu giống nhất… giữ nguyên tham số khác", lời nhắc sau READ chỉ lặp ví dụ đầu. 74% câu sai public chép hàm của ví dụ đầu.

## Quyết định

1. Prompt v11: chọn ví dụ cùng phép tính (cùng số đo, cách xếp hạng, dạng đáp án); ví dụ đầu không nhất thiết đúng.
2. Lời nhắc sau READ liệt kê đủ các ví dụ thay vì chỉ ví dụ đầu.

## Pattern và đánh đổi

Đánh đổi: model có thể bỏ một ví dụ đầu đúng (thấy ở `q_338d0179f66d` trên 100 câu thử).

## Đo sau khi áp dụng

EXP-20261107-04, 1000 câu public: tổng +0,849 so với +0,858 của EXP-03 cuối.

- 47 câu mất so với EXP-03; 38 câu trong đó ví dụ top-1 của EXP-04 đã cùng hàm với code đúng của EXP-03, model không theo.
- Code cuối cùng bộ hàm với ví dụ top-1: v10 805 câu, v11 782 câu; tự viết không theo ví dụ nào: v10 95, v11 119.
- 153 câu có 4 ví dụ y hệt EXP-03 (chỉ khác prompt): được 5, mất 10.

Kết luận: với gemma 12B, bỏ lời dặn chép ví dụ đầu làm model rời ví dụ và tự viết code, mất nhiều hơn phần được ở 13 câu ví dụ đúng nằm hạng 2–4. Bước xếp lại (ADR 014) đã đưa ví dụ đúng lên đầu, nên lời dặn "chép ví dụ đầu" của v10 nên giữ.
