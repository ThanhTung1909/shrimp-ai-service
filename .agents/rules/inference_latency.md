# Inference Latency Rule (Quy Tắc Độ Trễ Suy Luận)

1. Toàn bộ API suy luận của AI Service phải đạt thời gian phản hồi $t < 500\text{ ms}$ (P99 $< 500\text{ ms}$) để đáp ứng luồng thời gian thực của trang trại thông minh.
2. Trọng số mô hình (`.joblib`) và scaler phải được nạp sẵn vào bộ nhớ RAM khi FastAPI khởi động (`lifespan` handler).
3. Sử dụng tính toán vector hóa NumPy/Scipy và kỹ thuật async I/O cho Redis và RabbitMQ.
4. Caching kết quả dự báo mới nhất trên Redis để các client (Web Portal, Mobile App) truy xuất với độ trễ mili-giây.
