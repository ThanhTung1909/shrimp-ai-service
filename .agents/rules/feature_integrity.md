# Feature Integrity Rule (Quy Tắc Giữ Nguyên Biến Thực Nghiệm)

Mô hình XGBoost Feeding Forecast không được phép lược bỏ bất kỳ biến nào trong 7 biến thực nghiệm bắt buộc sau:
1. `shrimp_age`: Tuổi tôm (ngày tuổi tính từ khi thả giống).
2. `shrimp_weight`: Khối lượng tôm trung bình (g/con).
3. `do_min`: Giá trị nồng độ Oxy hòa tan tối thiểu quan sát được trong chu kỳ đo gần nhất (mg/L).
4. `tan_delta`: Độ biến thiên tổng amoniac TAN giữa 2 kỳ đo gần nhất từ nhật ký kiểm tra (mg/L).
5. `rain_0600`: **Lượng mưa lúc 06:00 sáng (mm)** - biến thực nghiệm tối quan trọng phản ánh hiện tượng tầng nước ao bị phân tầng, lạnh đột ngột và tôm bỏ ăn.
6. `previous_feed`: Lượng thức ăn cữ trước đã cho ăn (kg).
7. `water_exchange_ratio`: Tỷ lệ thay nước trong ngày (%).
