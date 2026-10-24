# Resource Isolation Rule (Quy Tắc Độc Lập Vi Dịch Vụ)

1. AI Service chạy hoàn toàn độc lập trên cổng **Port 8000**, trong một container riêng biệt.
2. Tuyệt đối không chia sẻ tiến trình trực tiếp với Core Backend NestJS (chạy Port 3000).
3. Đảm bảo luồng xử lý suy luận AI không can thiệp hay làm tắc nghẽn luồng tiếp nhận MQTT telemetry từ các thiết bị IoT ESP32.
4. Giao tiếp giữa Core Backend và AI Service thực hiện qua REST API chuẩn HTTP/JSON và hàng đợi sự kiện RabbitMQ bất đồng bộ.
