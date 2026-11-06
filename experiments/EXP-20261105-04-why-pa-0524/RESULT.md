# RESULT

Phân tích, không sửa code, không gọi model. Local sau khi tính cùng đối tượng là đúng: 758 đúng, 230 sai, 12 trống, PA 0.528; hệ thống chấm 0.524.

| Nguyên nhân | Câu | Trần PA |
|---|---|---|
| Thiếu helper | 122 | +0.235 |
| Model chọn sai hàm hoặc tham số | 101 | +0.200 |
| Trả lời câu đáng lẽ unanswerable | 19 | +0.037 |

Nhóm gán bằng regex, chỉ kiểm tay một phần. Câu oracle giải được: top-1 đúng intent 473/566; model đúng 465/473 khi top-1 đúng, 68/93 khi top-1 sai. Accuracy khi xong trong 2 lượt: public 0.809, 24 shop test 0.963.

Kết luận: giả thuyết đúng. 209/242 câu không đúng nằm ngoài vùng oracle giải được.
