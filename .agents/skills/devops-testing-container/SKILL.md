---
name: devops-testing-container
description: >-
  Kỹ năng tự động hóa kiểm thử pytest (toán học Benson & Krause, Pydantic, Latency, E2E),
  đóng gói Dockerfile tối ưu đa tầng (python:3.10-slim) và cấu hình docker-compose.yml độc lập.
---

# Kỹ Năng: DevOps, Tự Động Hóa Kiểm Thử & Đóng Gói Container

Kỹ năng này hướng dẫn DevOps-Infrastructure-Agent thực thi quy chuẩn hạ tầng:

## 1. Pytest Test Suite Tự Động (`tests/`)
- `test_benson_krause.py`:
  - Đối chiếu giá trị bão hòa $DO_{sat}$ với bảng chuẩn quốc tế (USGS Field Manual):
    - $T = 20^\circ\text{C}, S = 0\text{ ppt} \rightarrow 9.09 \pm 0.05\text{ mg/L}$
    - $T = 25^\circ\text{C}, S = 0\text{ ppt} \rightarrow 8.26 \pm 0.05\text{ mg/L}$
    - $T = 25^\circ\text{C}, S = 15\text{ ppt} \rightarrow 7.56 \pm 0.05\text{ mg/L}$
    - $T = 30^\circ\text{C}, S = 25\text{ ppt} \rightarrow 6.41 \pm 0.05\text{ mg/L}$
- `test_api_latency.py`:
  - Thực hiện benchmark 100 requests tới API suy luận.
  - Đo thời gian phản hồi: khẳng định $P99 < 500\text{ ms}$ (thông thường $< 50\text{ ms}$).
- `test_e2e_integration.py`:
  - Mô phỏng trọn vẹn chu trình: Core Backend NestJS Cronjob (30 phút/lần) $\rightarrow$ AI Service $\rightarrow$ Cập nhật Cache Redis $\rightarrow$ Bắn Alert RabbitMQ.

## 2. Dockerfile Multi-Stage (`python:3.10-slim`)
- Giai đoạn `builder`: Cài đặt `gcc`, `g++`, `libpq-dev`, build Python wheels.
- Giai đoạn `runtime`: Kế thừa `python:3.10-slim`, chỉ copy wheels và thư viện cần thiết, giữ dung lượng image $< 350\text{ MB}$.
- Tạo non-root user `appuser` chạy tiến trình ứng dụng.
- Cấu hình `EXPOSE 8000` và `HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/health || exit 1`.

## 3. Cấu Hình Docker Compose Tích Hợp
- Khai báo service `ai_service` trên cổng `8000:8000`.
- Kết nối vào mạng `shrimp_local_net` của hệ thống.
- Sử dụng biến môi trường từ `.env` trỏ tới `timescaledb:5432`, `redis:6379`, `rabbitmq:5672`.
