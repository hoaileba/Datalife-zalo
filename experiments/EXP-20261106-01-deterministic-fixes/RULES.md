# RULES

1. Chỉ sửa lỗi tất định đã có bằng chứng ở bước dò (`probe24`): không đổi prompt, không đổi thư viện ví dụ, không thêm luật `unanswerable`.
2. Luật thêm vào phải dựa trên rulebook hoặc README của shop, không dựa trên đáp án Claude.
3. Đo `oracle.py` trước và sau trên train (gold) và public (bản Claude); câu nào từ đúng thành sai thì phải giải thích hoặc hoàn lại.
4. Ngoại lệ luật "một thực nghiệm đổi một thứ": gộp nhiều sửa lỗi nhỏ, gán kết quả theo từng câu qua `oracle` và probe.
5. Tối đa 5 luồng, `nice -n 10`; kiểm tra tiến trình đang chạy và load trước khi chạy.
6. `test_*` chỉ dùng để đo.
