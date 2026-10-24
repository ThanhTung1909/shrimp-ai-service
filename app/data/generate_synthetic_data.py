"""
Module sinh dữ liệu thực nghiệm nuôi tôm chuẩn khoa học
Mô phỏng chu kỳ nuôi tôm thẻ chân trắng (Litopenaeus vannamei) 90 ngày tại Đồng bằng Sông Cửu Long.
Phục vụ huấn luyện mô hình XGBoost Feeding và kiểm định Data Pipeline.
"""

import math
import numpy as np
import pandas as pd
from typing import Optional


def von_bertalanffy_weight(age_days: float, w_inf: float = 30.0, k: float = 0.026) -> float:
    """
    Ước tính trọng lượng trung bình tôm (g/con) theo hàm sinh trưởng von Bertalanffy:
    W(t) = W_inf * (1 - exp(-k * t))^3
    """
    if age_days <= 0:
        return 0.05
    val = 1.0 - math.exp(-k * age_days)
    if val <= 0:
        return 0.05
    weight = w_inf * (val ** 3)
    return max(0.05, weight)


def generate_synthetic_feeding_dataset(
    num_ponds: int = 10,
    cycle_days: int = 90,
    feeds_per_day: int = 4,
    random_seed: int = 42,
) -> pd.DataFrame:
    """
    Tạo bộ dữ liệu thực nghiệm chuỗi thời gian bao gồm 7 đặc trưng bắt buộc và biến mục tiêu feed_amount_kg.
    
    Các yếu tố sinh học thực tế:
    1. Đường cong tăng trưởng von Bertalanffy của tôm thẻ.
    2. Tỷ lệ cho ăn theo % khối lượng thân (giảm dần từ 9% ở giai đoạn giống xuống 2.8% ở cuối vụ).
    3. Biến rain_0600: Mưa lúc 06:00 sáng làm giảm nhiệt độ mặt nước và pH, khiến tôm sốc và bỏ ăn 20-50%.
    4. Biến do_min: Oxy thấp (< 4.0 mg/L) giảm sức ăn; cực thấp (< 3.0 mg/L) tôm ngạt và ngừng ăn.
    5. Biến tan_delta: TAN tích tụ đột ngột gây độc, giảm khẩu phần ăn.
    6. Biến water_exchange_ratio: Thay nước giúp kích thích tôm lột xác và ăn bù.
    7. Biến previous_feed: Tính liên tục tự tương quan của cữ ăn trước.
    """
    np.random.seed(random_seed)
    records = []

    # Giả định diện tích ao trung bình 2,500 m2, mật độ 160 con/m2 -> ~400,000 con
    pond_area_m2 = 2500.0
    stocking_density = 160

    feed_times = ["07:00", "11:00", "15:00", "19:00"]
    # Trong mô hình dinh dưỡng chuẩn, khẩu phần hàng ngày được phân bổ đồng đều qua các cữ (mỗi cữ 25%)
    # Giúp previous_feed duy trì tính tự tương quan nhất quán với cữ hiện tại
    feed_proportions = [0.25, 0.25, 0.25, 0.25]

    for pond_idx in range(1, num_ponds + 1):
        pond_id = f"pond-{pond_idx:03d}"
        pond_density = stocking_density + np.random.randint(-15, 15)
        total_shrimp = pond_area_m2 * pond_density

        current_feed = 5.0  # Cữ ăn đầu tiên cữ nhỏ

        for day in range(1, cycle_days + 1):
            shrimp_age = float(day)
            
            # 1. Trọng lượng tôm theo tuổi với nhiễu ngẫu nhiên cá thể ±2%
            base_weight = von_bertalanffy_weight(shrimp_age)
            shrimp_weight = round(base_weight * np.random.uniform(0.98, 1.02), 2)

            # Tổng sinh khối (kg) = số lượng * cân nặng (g) / 1000
            biomass_kg = (total_shrimp * shrimp_weight) / 1000.0

            # Tỷ lệ % thức ăn theo cân nặng cơ thể (Body Weight Ratio)
            # Tôm nhỏ ăn 8-9% body weight, tôm lớn ~30g ăn 2.8% body weight
            body_weight_feed_pct = max(0.028, 0.088 * math.exp(-0.014 * shrimp_age))
            base_daily_feed = biomass_kg * body_weight_feed_pct

            # 2. Yếu tố mưa lúc 06:00 sáng (rain_0600)
            # Khoảng 22% số ngày có mưa sáng ở ĐBSCL
            is_rainy_morning = np.random.rand() < 0.22
            if is_rainy_morning:
                rain_0600 = round(float(np.random.exponential(scale=16.0) + 5.0), 1)
            else:
                rain_0600 = 0.0

            # 3. Yếu tố thay nước trong ngày (%)
            # Thay nước định kỳ mỗi 5-6 ngày hoặc sau mưa lớn
            if day % 6 == 0 or (is_rainy_morning and np.random.rand() < 0.4):
                water_exchange_ratio = round(float(np.random.uniform(5.0, 16.0)), 1)
            else:
                water_exchange_ratio = 0.0

            # 4. Yếu tố DO tối thiểu (do_min)
            # Ban đêm DO giảm, trung bình 4.5 - 6.0 mg/L; ngày mưa tảo tàn DO có thể tụt xuống 3.2 - 4.2 mg/L
            if is_rainy_morning:
                do_min = round(float(np.random.uniform(3.2, 4.2)), 2)
            else:
                do_min = round(float(np.random.uniform(4.4, 6.0)), 2)

            # 5. Yếu tố biến thiên TAN (tan_delta)
            # Đa phần ổn định quanh 0; thỉnh thoảng tăng vọt do thức ăn thừa hoặc tảo tàn
            if day > 25 and np.random.rand() < 0.12:
                tan_delta = round(float(np.random.uniform(0.15, 0.50)), 3)
            elif np.random.rand() < 0.10:
                tan_delta = round(float(np.random.uniform(-0.25, -0.05)), 3)  # Giảm do xử lý vi sinh
            else:
                tan_delta = round(float(np.random.normal(0.0, 0.04)), 3)

            # Tạo dữ liệu cho từng cữ ăn trong ngày
            for c_idx, (ftime, prop) in enumerate(zip(feed_times, feed_proportions)):
                c_base_feed = base_daily_feed * prop

                # --- HỆ SỐ ĐIỀU CHỈNH THỰC NGHIỆM ---
                factor = 1.0

                # Ảnh hưởng mưa 06:00 sáng: tác động mạnh nhất vào cữ 1 (07:00) và cữ 2 (11:00)
                if rain_0600 > 0:
                    if c_idx == 0:  # Cữ 07:00 sáng chịu ảnh hưởng trực tiếp nhất
                        rain_penalty = min(0.40, 0.015 * rain_0600 + 0.12)
                        factor *= (1.0 - rain_penalty)
                    elif c_idx == 1: # Cữ trưa vẫn còn ảnh hưởng
                        rain_penalty = min(0.20, 0.008 * rain_0600 + 0.06)
                        factor *= (1.0 - rain_penalty)

                # Ảnh hưởng DO tối thiểu:
                if do_min < 3.5:
                    factor *= 0.55  # Tôm ngạt nặng, cắt giảm 45%
                elif do_min < 4.2:
                    factor *= 0.82  # Oxy thấp, giảm 18%

                # Ảnh hưởng khí độc TAN:
                if tan_delta > 0.2:
                    factor *= 0.85  # Khí độc tăng nhanh, giảm 15%

                # Ảnh hưởng thay nước:
                if water_exchange_ratio > 8.0:
                    factor *= 1.04  # Nước mới kích thích tôm bắt mồi tốt hơn

                # Nhiễu thực nghiệm tự nhiên nhỏ ±2%
                experimental_noise = np.random.normal(1.0, 0.02)
                factor *= experimental_noise

                # Tính lượng thức ăn thực tế khuyến nghị cho cữ này
                feed_amount_kg = max(1.0, round(c_base_feed * factor, 2))

                records.append({
                    "pond_id": pond_id,
                    "day": day,
                    "feed_time": ftime,
                    # 7 biến thực nghiệm bắt buộc
                    "shrimp_age": shrimp_age,
                    "shrimp_weight": shrimp_weight,
                    "do_min": do_min,
                    "tan_delta": tan_delta,
                    "rain_0600": rain_0600,
                    "previous_feed": round(current_feed, 2),
                    "water_exchange_ratio": water_exchange_ratio,
                    # Biến mục tiêu
                    "feed_amount_kg": feed_amount_kg,
                })

                current_feed = feed_amount_kg

    df = pd.DataFrame(records)
    return df


if __name__ == "__main__":
    df = generate_synthetic_feeding_dataset(num_ponds=5, cycle_days=90)
    print(f"Đã tạo bộ dữ liệu thực nghiệm: {df.shape[0]} dòng, {df.shape[1]} cột.")
    print("Mẫu dữ liệu:")
    print(df.head())
    print("\nThống kê mô tả 7 đặc trưng thực nghiệm và biến mục tiêu:")
    print(df.describe().T[["mean", "std", "min", "50%", "max"]])
