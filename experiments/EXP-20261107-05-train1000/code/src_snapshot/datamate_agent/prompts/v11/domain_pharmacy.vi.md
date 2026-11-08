Lô và hạn dùng:
- `expiring_lots(90)`, `expiring_value(90)`, `expiring_items(90)`: số lô, tiền vốn, danh sách hàng còn tồn hết hạn trong 90 ngày tới. Có khoảng ngày thì `expiring_lots(start="2026-08-08", end="2026-12-06")`.
- `nearest_expiry("Tên hàng")`: hạn của lô gần hết hạn nhất. `out_of_stock_count("2026-06-01")`: số mặt hàng hết hàng cuối ngày.
