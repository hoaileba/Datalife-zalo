# RULES

1. Code hoá trong lần chạy này: §1 doanh thu, số đơn, tỉ lệ huỷ; §2 các kỳ; §3 phần xếp hạng, ở `src/datamate/shop.py`, `src/datamate/periods.py`.
2. Cố ý chưa làm: helper cho nợ, kho, lô, giá vốn, lãi, quy đổi đơn vị khi shop không có cột đã quy đổi, tách topping; các phần này model tự viết từ `lines`, `tables`.
3. Quyết định tạm chưa thành ADR: không dùng LLM map cột; từ chối `read_csv` trên `norm/`.
