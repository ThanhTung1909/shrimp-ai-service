---
name: xgboost-feeding-modeling
description: >-
  Kỹ năng huấn luyện mô hình XGBoost dự báo lượng thức ăn cho tôm với bộ siêu tham số
  thực nghiệm (R2 >= 0.78, MAPE <= 8.7%), và xây dựng AI Soft Sensor theo phương trình lý hóa
  Benson & Krause (1984) để ước lượng DO bão hòa và phân tích suy giảm oxy ban đêm.
---

# Kỹ Năng: Huấn Luyện XGBoost Feeding Model & AI Soft Sensor

Kỹ năng này hướng dẫn ML-Modeling-Agent xây dựng và kiểm định mô hình học máy:

## 1. Cấu Hình Mô Hình XGBoost Thực Nghiệm
Khởi tạo `XGBRegressor` với bộ tham số thực nghiệm bắt buộc:
```python
from xgboost import XGBRegressor

model = XGBRegressor(
    n_estimators=600,
    learning_rate=0.05,
    max_depth=6,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    objective="reg:squarederror"
)
```

## 2. Tiêu Chí Đánh Giá Khoa Học (Acceptance Criteria)
Đánh giá trên tập test độc lập:
- $R^2 \ge 0.78$
- $\text{MAPE} \le 8.7\%$
- Đo lường bổ sung: $\text{MAE}$ (Mean Absolute Error).
- Xuất kết quả vào `model_metadata.json`.

## 3. AI Soft Sensor: Phương Trình Benson & Krause (1984)
Tính toán nồng độ Oxy hòa tan bão hòa lý thuyết ($C^*$ hay $DO_{sat}$ tính bằng mg/L) ở áp suất tiêu chuẩn 1 atm:
```python
import numpy as np

def calculate_do_saturation(temp_celsius: float, salinity_ppt: float) -> float:
    t_k = temp_celsius + 273.15
    ln_c_star = (
        -139.34411
        + (1.575701e5 / t_k)
        - (6.642308e7 / (t_k ** 2))
        + (1.243800e10 / (t_k ** 3))
        - (8.621949e11 / (t_k ** 4))
        - salinity_ppt * (0.017674 - (10.754 / t_k) + (2140.7 / (t_k ** 2)))
    )
    return float(np.exp(ln_c_star))
```

## 4. Phân Tích Suy Giảm Oxy Đêm (Nighttime DO Depletion Analysis)
- Ban đêm (18:00 - 06:00), tảo ngừng quang hợp và chuyển sang hô hấp tiêu thụ oxy cùng tôm và mùn bã hữu cơ đáy ao.
- Mô hình tính toán độ dốc suy giảm $\frac{d(DO)}{dt}$.
- Nếu dự báo nồng độ oxy chạm ngưỡng nguy hiểm ($< 3.5\text{ mg/L}$) trong khoảng 01:00 - 05:00 sáng, kích hoạt cờ cảnh báo `risk_level = "HIGH"` để đẩy sang RabbitMQ.
