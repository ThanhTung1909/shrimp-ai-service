---
name: fastapi-redis-rabbitmq
description: >-
  Kỹ năng xây dựng API FastAPI trên cổng 8000 đạt độ trễ < 500ms, kiểm tra Pydantic schemas,
  kết nối Redis async caching và cơ chế phát sự kiện bất đồng bộ qua RabbitMQ (aio-pika).
---

# Kỹ Năng: Tích Hợp FastAPI, Redis & RabbitMQ Event-Driven

Kỹ năng này hướng dẫn Backend-Integration-Agent triển khai kiến trúc vi dịch vụ hiệu năng cao:

## 1. Đảm Bảo Độ Trễ Suy Luận < 500ms (Inference Latency Rule)
- Khởi tạo FastAPI `lifespan`: Tải trước toàn bộ mô hình (`.joblib`), `StandardScaler`, và kết nối pool (Redis, RabbitMQ) vào `app.state` ngay khi server khởi động.
- Tránh IO blocking: Toàn bộ xử lý I/O (Redis, RabbitMQ, HTTP) đều dùng thư viện `asyncio`.
- Vector hóa dữ liệu đầu vào: Chuyển payload sang NumPy 2D array và chạy `predict()` trực tiếp trong bộ nhớ RAM, thời gian tính toán mô hình $< 10\text{ ms}$.

## 2. Pydantic Validation Chặt Chẽ
- Validate kiểu dữ liệu và biên số học sinh học cho ao nuôi tôm:
  - `shrimp_age`: $1 \le \text{age} \le 180$
  - `shrimp_weight`: $0.1 \le \text{weight} \le 100.0$
  - `rain_0600`: $\ge 0.0$
  - `do_min`: $0.0 \le \text{DO} \le 15.0$
- Tương thích 100% với định dạng JSON từ Core Backend NestJS (`PredictionsService`).

## 3. Redis Async Caching
- Key cấu trúc:
  - `ai:forecast:feeding:{pond_id}`
  - `ai:forecast:water:{pond_id}`
- TTL: 1800 giây (30 phút, đồng bộ với chu kỳ Cronjob của Core Backend).
- Giúp Web Portal và Mobile App đọc ngay kết quả dự báo trong $< 5\text{ ms}$.

## 4. RabbitMQ Event-Driven Messaging (`aio-pika`)
- Kết nối tới RabbitMQ AMQP `5672`.
- Khai báo Exchange `shrimp.events` (loại `topic` hoặc `direct`) và Queue `ai_risk_alerts`.
- Khi phát hiện rủi ro cao hoặc quỹ đạo DO đêm tụt dốc nguy hiểm, đẩy message dạng JSON:
  ```json
  {
    "event": "ai.risk.detected",
    "pond_id": "...",
    "risk_level": "HIGH",
    "predicted_metric": "dissolved_oxygen",
    "predicted_value": 2.8,
    "warning_time": "2026-10-10T03:30:00Z",
    "action_suggestion": "Bật quạt nước phụ và cấp oxy viên ngay lập tức.",
    "timestamp": "..."
  }
  ```
