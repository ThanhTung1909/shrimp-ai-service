# HỆ THỐNG QUY TẮC, VAI TRÒ AGENT & NHIỆM VỤ DỰ ÁN AI SERVICE

Tài liệu này ghi nhớ toàn diện các quy tắc vận hành chung (Global Rules & Guardrails), định nghĩa 4 AI Agent chuyên trách, bộ kỹ năng chuyên môn (Skills), cấu trúc hệ thống và danh sách nhiệm vụ chi tiết (Task Breakdown) cho hệ thống **AquaSense AI Microservice**.

---

## I. Khung Pháp Lý & Quy Tắc Vận Hành Chung (Global Rules & Guardrails)

1. **Quy tắc Chống rò rỉ dữ liệu (Anti-Data Leakage Rule)**:
   - Tuyệt đối không dùng `train_test_split` ngẫu nhiên trên dữ liệu cảm biến chuỗi thời gian (time-series).
   - Bắt buộc áp dụng Rolling-origin Cross-validation (`TimeSeriesSplit`) hoặc Time-blocked Split.
   - `StandardScaler` và các kỹ thuật tiền xử lý chỉ được phép khớp (fit) trên tập huấn luyện (`train set`), sau đó dùng `transform` trên tập kiểm thử (`test set`).

2. **Quy tắc Độ trễ (Inference Latency Rule)**:
   - Toàn bộ API suy luận của AI Service phải đạt thời gian phản hồi $< 500\text{ ms}$ để đáp ứng luồng thời gian thực của trang trại.
   - Trọng số mô hình (`.joblib`) phải được tải sẵn vào bộ nhớ RAM khi ứng dụng khởi động (FastAPI lifespan).

3. **Quy tắc Giữ nguyên Biến thực nghiệm (Feature Integrity Rule)**:
   - Mô hình XGBoost dự báo thức ăn không được tự ý lược bỏ bất kỳ biến nào trong 7 biến thực nghiệm bắt buộc:
     1. `shrimp_age`: Tuổi tôm (ngày)
     2. `shrimp_weight`: Khối lượng tôm trung bình (g/con)
     3. `do_min`: Nồng độ Oxy hòa tan tối thiểu trong 12h/24h qua (mg/L)
     4. `tan_delta`: Độ biến thiên tổng amoniac TAN giữa 2 chu kỳ đo gần nhất (mg/L)
     5. `rain_0600`: **Lượng mưa lúc 06:00 sáng (mm)** - biến tiên quyết phản ánh hiện tượng tôm sốc môi trường và bỏ ăn đột ngột
     6. `previous_feed`: Lượng thức ăn cữ trước (kg)
     7. `water_exchange_ratio`: Tỷ lệ thay nước trong ngày (%)

4. **Quy tắc Độc lập Vi dịch vụ (Resource Isolation Rule)**:
   - AI Service chạy hoàn toàn độc lập trên cổng riêng **Port 8000**, container riêng biệt.
   - Tuyệt đối không chia sẻ tiến trình trực tiếp với Core Backend NestJS để tránh gây nghẽn luồng xử lý MQTT của hệ thống IoT.

---

## II. Phân Rã Vai Trò Agent & Bộ Kỹ Năng Chuyên Môn (Agent Roles & Skills)

### 1. Agent 1: Data-Pipeline-Agent (Kỹ sư Dữ liệu)
- **Kỹ năng cốt lõi (Skills)**: Python, Pandas, NumPy, TimescaleDB SQL, SQLAlchemy, Time-series Interpolation, Rolling-origin Split, Data Leakage Prevention.
- **Nhiệm vụ trọng tâm**: Quản lý vòng đời dữ liệu từ lúc trích xuất từ TimescaleDB, làm sạch, xử lý khuyết tật bằng nội suy tuyến tính đến khi chuẩn hóa và sẵn sàng đưa vào mô hình học máy.

### 2. Agent 2: ML-Modeling-Agent (Kỹ sư Học máy & Mô hình)
- **Kỹ năng cốt lõi (Skills)**: Scikit-learn, XGBoost Regressor, NumPy, Hyperparameter Tuning, Evaluation Metrics (MAE, MAPE, $R^2$), Benson & Krause Thermodynamic Modeling, Model Serialization.
- **Nhiệm vụ trọng tâm**: Huấn luyện mô hình XGBoost Feeding bám sát tham số thực nghiệm (đạt $R^2 \ge 0.78$, $\text{MAPE} \le 8.7\%$), phát triển AI Soft Sensor bão hòa DO và đánh giá quỹ đạo suy giảm oxy ban đêm.

### 3. Agent 3: Backend-Integration-Agent (Kỹ sư Tích hợp Hệ thống)
- **Kỹ năng cốt lõi (Skills)**: FastAPI, Pydantic Data Validation, Redis Caching (async), RabbitMQ Event-driven Messaging (`aio-pika`), Uvicorn, REST API Architecture.
- **Nhiệm vụ trọng tâm**: Đóng gói mô hình thành các API RESTful tốc độ cao ($< 500\text{ ms}$), kết nối caching Redis lưu kết quả dự báo và đẩy sự kiện cảnh báo sớm (AI Risk Detected) sang RabbitMQ.

### 4. Agent 4: DevOps-Infrastructure-Agent (Kỹ sư Hạ tầng & Vận hành)
- **Kỹ năng cốt lõi (Skills)**: Docker Multi-stage Build, Docker-Compose, Pytest Automation, Pytest-asyncio, CI/CD Pipeline, Performance Benchmarking.
- **Nhiệm vụ trọng tâm**: Đóng gói container an toàn và nhẹ dựa trên `python:3.10-slim`, kiểm thử tự động toàn diện và đảm bảo tính sẵn sàng cao khi tích hợp cùng TimescaleDB, Redis, RabbitMQ.

---

## III. Bảng Phân Rã Task Chi Tiết Theo 4 Pha (Task Breakdown)

### Pha 1: Chuẩn bị Dữ liệu & Pipeline (Data-Pipeline-Agent)
- **TASK-DP-01**: Thiết lập kết nối cơ sở dữ liệu TimescaleDB từ Python, viết câu lệnh SQL truy xuất chuỗi thời gian telemetry (`temperature`, `ph`, `salinity`, `dissolved_oxygen`, `turbidity`) theo từng ao (`pond_id`) và `time_bucket`.
- **TASK-DP-02**: Xây dựng module làm sạch dữ liệu (`app/services/pipeline.py`), tích hợp hàm nội suy tuyến tính (`linear interpolation`) để xử lý các điểm dữ liệu bị khuyết.
- **TASK-DP-03**: Lập trình pipeline trích xuất 7 đặc trưng thực nghiệm (`Features Extraction`) cho mô hình dự báo thức ăn: `shrimp_age`, `shrimp_weight`, `do_min`, `tan_delta`, `rain_0600`, `previous_feed`, `water_exchange_ratio`.
- **TASK-DP-04**: Áp dụng phương pháp phân chia tập dữ liệu theo thời gian (`time-blocked cross-validation` / `TimeSeriesSplit`) và cấu hình `StandardScaler` chống rò rỉ dữ liệu.

### Pha 2: Huấn luyện & Tối ưu Mô hình AI (ML-Modeling-Agent)
- **TASK-ML-01**: Xây dựng script huấn luyện mô hình XGBoost Feeding Model (`app/models/xgboost_feeding.py`) bám sát tham số thực nghiệm: `n_estimators=600`, `learning_rate=0.05`, `max_depth=6`, `subsample=0.8`, `colsample_bytree=0.8`.
- **TASK-ML-02**: Đánh giá độ chính xác mô hình trên tập kiểm thử, đảm bảo đạt chuẩn khoa học ($R^2 \ge 0.78$, $\text{MAPE} \le 8.7\%$).
- **TASK-ML-03**: Phát triển mô hình AI Soft Sensor kết hợp phương trình lý hóa Benson & Krause (1984) để ước lượng giá trị $DO_{sat}$ bão hòa dựa trên Nhiệt độ và Độ mặn, giúp tối ưu chi phí phần cứng và dự báo nguy cơ thiếu hụt oxy ban đêm.
- **TASK-ML-04**: Đóng gói và xuất file trọng số mô hình (`.joblib`) vào thư mục `trained_models/` kèm `model_metadata.json`.

### Pha 3: Xây dựng API & Tích hợp Bất đồng bộ (Backend-Integration-Agent)
- **TASK-BE-01**: Khởi tạo khung ứng dụng Python FastAPI (`app/main.py`), cấu hình Global Exception Handler, CORS Middleware và Lifespan preloading.
- **TASK-BE-02**: Xây dựng các Pydantic Schemas (`app/schemas/`) để kiểm tra tính hợp lệ chặt chẽ của dữ liệu đầu vào từ Core Backend NestJS.
- **TASK-BE-03**: Phát triển REST API endpoints:
  - `POST /api/v1/ai/forecast-feeding`: Trả về lượng thức ăn khuyến nghị và `risk_level` trong $< 500\text{ ms}$.
  - `POST /api/predict`: Tương thích 100% với NestJS `PredictionsService` (`predictedDO`, `predictedPH`, `riskScore`, `riskLevel`).
  - `POST /api/v1/ai/soft-sensor/do-saturation`: Ước lượng độ bão hòa $DO$ và mức thiếu hụt oxy.
  - `GET /health`: Health check service, Redis, RabbitMQ.
- **TASK-BE-04**: Tích hợp Redis Cache để lưu trữ kết quả dự báo mới nhất, giúp Web Portal và Mobile App truy xuất với tốc độ mili-giây.
- **TASK-BE-05**: Lập trình cơ chế đẩy sự kiện cảnh báo sớm (AI Risk Detected) vào hàng đợi RabbitMQ (`aio-pika`) khi phát hiện quỹ đạo $DO$ giảm nguy hiểm vào ban đêm.

### Pha 4: Kiểm thử, Đóng gói Hạ tầng & Bàn giao (DevOps-Infrastructure-Agent)
- **TASK-DEV-01**: Viết bộ Unit Test tự động bằng `pytest` (`tests/`) để kiểm tra độ chính xác của hàm Benson & Krause, Pydantic Schemas, Pipeline và Latency.
- **TASK-DEV-02**: Viết Dockerfile tối ưu hóa kích thước image (sử dụng base image `python:3.10-slim`, multi-stage).
- **TASK-DEV-03**: Cấu hình file `docker-compose.yml` tích hợp toàn diện AI Service chạy đồng bộ cùng TimescaleDB, Redis, RabbitMQ và Mosquitto trên mạng `shrimp_local_net`.
- **TASK-DEV-04**: Thực hiện kiểm thử tích hợp End-to-End (E2E) mô phỏng luồng từ Core Backend gửi lệnh kích hoạt (Orchestrator cronjob 30 phút/lần) sang AI Service và nhận lại kết quả thành công trong $< 500\text{ ms}$.

---

## IV. Cấu Trúc Hệ Thống & Cây Thư Mục (Codebase Architecture)

```
ai_service/
├── .agents/
│   ├── rules/                      # Quy tắc dự án
│   └── skills/                     # Kỹ năng chuyên môn
├── app/
│   ├── __init__.py
│   ├── main.py                     # Entrypoint FastAPI, lifespan, middleware
│   ├── config.py                   # Pydantic Settings đọc cấu hình .env
│   ├── database.py                 # Kết nối TimescaleDB & Redis
│   ├── api/
│   │   ├── deps.py                 # Dependency injection
│   │   └── v1/
│   │       ├── router.py           # Router tổng
│   │       ├── feeding.py          # /api/v1/ai/forecast-feeding
│   │       ├── predictions.py      # /api/predict (NestJS compatibility)
│   │       └── soft_sensor.py      # /api/v1/ai/soft-sensor/do-saturation
│   ├── schemas/
│   │   ├── feeding.py              # Schema thức ăn & rủi ro
│   │   ├── prediction.py           # Schema chất lượng nước
│   │   └── soft_sensor.py          # Schema Benson & Krause
│   ├── services/
│   │   ├── pipeline.py             # Làm sạch, nội suy, trích xuất đặc trưng
│   │   ├── redis_cache.py          # Redis caching service
│   │   └── rabbitmq_publisher.py   # Asynchronous RabbitMQ publisher
│   ├── models/
│   │   ├── xgboost_feeding.py      # Mô hình XGBoost & trainer
│   │   └── soft_sensor.py          # Phương trình Benson & Krause
│   └── data/
│       └── generate_synthetic_data.py # Bộ dữ liệu sinh thực nghiệm
├── trained_models/
│   ├── xgboost_feeding_model.joblib
│   ├── feeding_scaler.joblib
│   └── model_metadata.json
├── tests/
│   ├── test_benson_krause.py
│   ├── test_pipeline.py
│   ├── test_schemas.py
│   ├── test_api_latency.py
│   └── test_e2e_integration.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```
