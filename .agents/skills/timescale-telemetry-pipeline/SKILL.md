---
name: timescale-telemetry-pipeline
description: >-
  Kỹ năng thu thập, làm sạch và xử lý chuỗi thời gian telemetry từ TimescaleDB,
  thực hiện nội suy tuyến tính (linear interpolation), trích xuất 7 đặc trưng thực nghiệm
  cho ao tôm và phân chia time-series cross-validation chống rò rỉ dữ liệu.
---

# Kỹ Năng: TimescaleDB Telemetry Pipeline & Feature Extraction

Kỹ năng này hướng dẫn Data-Pipeline-Agent thực hiện quy trình xử lý dữ liệu chuẩn khoa học:

## 1. Truy Vấn TimescaleDB Theo Time Bucket
- Kết nối tới TimescaleDB (PostgreSQL 16) qua SQLAlchemy/psycopg2.
- Truy vấn bảng `telemetry_data` kết hợp `pond` và `device`.
- Sử dụng hàm TimescaleDB `time_bucket('15 minutes', recorded_at)` để gom cụm và làm mượt chuỗi thời gian.

## 2. Làm Sạch & Nội Suy Tuyến Tính (Linear Interpolation)
- Phát hiện các điểm khuyết (NaN) do rớt gói mạng IoT (ESP32).
- Áp dụng `df.interpolate(method='linear', limit=8)` (tối đa 2 giờ khuyết). Nếu vượt quá ngưỡng trôi dạt 2 giờ, đánh dấu flag dữ liệu không liên tục để xử lý riêng.
- Lọc nhiễu cảm biến theo biên sinh học:
  - Nhiệt độ: 15.0°C - 42.0°C
  - pH: 5.5 - 10.0
  - Độ mặn: 0.0 - 45.0 ppt
  - DO: 0.0 - 15.0 mg/L

## 3. Trích Xuất 7 Biến Thực Nghiệm (Feature Integrity Rule)
Tuyệt đối không bỏ sót biến nào:
1. `shrimp_age`: Tuổi tôm tính từ ngày thả giống.
2. `shrimp_weight`: Khối lượng tôm trung bình (g/con).
3. `do_min`: Giá trị DO thấp nhất trong 12h/24h qua.
4. `tan_delta`: Biến thiên chỉ số khí độc TAN giữa 2 lần đo gần nhất từ `manual_test_log`.
5. `rain_0600`: Lượng mưa lúc 06:00 sáng (mm). **Biến tối quan trọng do nước mưa làm hạ nhiệt tầng mặt và biến động pH, khiến tôm ngừng ăn**.
6. `previous_feed`: Khối lượng thức ăn cữ trước (kg).
7. `water_exchange_ratio`: Tỷ lệ phần trăm thể tích ao được thay nước trong ngày (%).

## 4. Chống Rò Rỉ Dữ Liệu (Anti-Data Leakage Rule)
- Bắt buộc dùng `TimeSeriesSplit(n_splits=5)`:
  - Fold $k$: Train trên khoảng $[0, t_k]$, Test trên $[t_k, t_{k+1}]$.
- `StandardScaler`:
  ```python
  scaler = StandardScaler()
  X_train_scaled = scaler.fit_transform(X_train)
  X_test_scaled = scaler.transform(X_test) # CHỈ TRANSFORM, KHÔNG FIT!
  ```
- Lưu `scaler` ra file `trained_models/feeding_scaler.joblib`.
