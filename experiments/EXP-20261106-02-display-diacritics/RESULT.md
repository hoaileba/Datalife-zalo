# RESULT

| Số đo | Trước (EXP-20261106-01) | Sau |
|---|---|---|
| oracle_train_right | 2201/3000 | 2204/3000 |
| oracle_public_right | 570/1000 | 570/1000 |
| oracle_regressions | | 0 train, 0 public (sau khi sửa lỗi `max()` rỗng ở biz_123) |
| accent_lost_cells | public 0/205, test 0/69 ô chữ mất dấu | tên ở biz_106/108/119/120/128/dev_002/dev_014: 55 tên thêm dấu, 125 tên đổi về cách ghi của danh mục, 0 tên xấu đi |
| pa_public (chạy lại code FINAL cũ, không gọi LLM; error/replay.py) | 0.845 | 0.849 (+2 câu sửa xe mà EXP-01 bỏ sót, 4 câu đổi tên có dấu) |

Sự cố: luật "ưu tiên chữ hoa đầu" đổi `iPhone 13` thành `Iphone 13`, đã bỏ luật đó (bộ chấm không phân biệt hoa thường). `display_name` lần đầu chạy trên toàn bộ `lines` mỗi lần gọi `ranking`, làm oracle train mất khoảng 10 phút; đã cache theo `Shop`, còn 4 phút 50 giây. Lần đầu oracle train mất 2 câu biz_123 vì `max()` gặp danh sách rỗng; đã bỏ dòng không có tên, chạy lại 0 câu từ đúng thành sai.

Kết luận: giả thuyết đúng. Chưa chạy agent; số public là chạy lại code FINAL cũ.
