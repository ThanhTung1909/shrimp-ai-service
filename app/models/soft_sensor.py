"""
AI Soft Sensor: Nồng độ Oxy hòa tan bão hòa Benson & Krause (1984)
và Mô hình Đánh giá Quỹ đạo Suy giảm Oxy Ban Đêm (Nighttime DO Depletion).
Do ML-Modeling-Agent chủ trì.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger("ai_service.models.soft_sensor")

# Các hệ số nhiệt động học Benson & Krause (1984) cho Oxy hòa tan ở 1 atm
A0 = -139.34411
A1 = 1.575701e5
A2 = -6.642308e7
A3 = 1.243800e10
A4 = -8.621949e11

# Hệ số hiệu chỉnh độ mặn (Salinity correction factors)
B0 = 0.017674
B1 = -10.754
B2 = 2140.7


def calculate_do_saturation(
    temperature: float,
    salinity: float = 0.0,
    pressure_atm: float = 1.0,
) -> float:
    """
    Tính nồng độ Oxy hòa tan bão hòa lý thuyết (DO_sat, mg/L) theo phương trình Benson & Krause (1984).
    
    Phương trình chuẩn quốc tế (USGS, Standard Methods):
    ln(C*) = A0 + A1/T_K - A2/T_K^2 + A3/T_K^3 - A4/T_K^4 - S * (B0 + B1/T_K + B2/T_K^2)
    
    Args:
        temperature: Nhiệt độ nước (°C). Giới hạn kiểm tra: 0.0 đến 45.0 °C.
        salinity: Độ mặn nước (ppt hoặc g/kg). Giới hạn: 0.0 đến 45.0 ppt.
        pressure_atm: Áp suất khí quyển (atm, mặc định: 1.0 atm = 101.325 kPa).
        
    Returns:
        float: Nồng độ DO bão hòa (mg/L), làm tròn 3 chữ số thập phân.
    """
    if not (0.0 <= temperature <= 50.0):
        raise ValueError(f"Nhiệt độ ngoài dải áp dụng (0 - 50°C): {temperature}°C")
    if not (0.0 <= salinity <= 50.0):
        raise ValueError(f"Độ mặn ngoài dải áp dụng (0 - 50 ppt): {salinity} ppt")
    if pressure_atm <= 0.0:
        raise ValueError(f"Áp suất khí quyển phải > 0 atm: {pressure_atm}")

    # Nhiệt độ tuyệt đối Kelvin
    t_k = temperature + 273.15

    # Tính hàm số theo nhiệt độ
    temp_term = (
        A0
        + (A1 / t_k)
        + (A2 / (t_k ** 2))
        + (A3 / (t_k ** 3))
        + (A4 / (t_k ** 4))
    )

    # Hiệu chỉnh độ mặn
    sal_term = salinity * (B0 + (B1 / t_k) + (B2 / (t_k ** 2)))

    # ln(C*) ở 1 atm
    ln_c_star = temp_term - sal_term
    c_star_1atm = np.exp(ln_c_star)

    # Hiệu chỉnh áp suất khí quyển (nếu khác 1 atm)
    # P_wv: Áp suất hơi nước bão hòa theo Arden Buck
    p_wv = 0.0061121 * np.exp((18.678 - (temperature / 234.5)) * (temperature / (257.14 + temperature)))
    pressure_correction = (pressure_atm - p_wv) / (1.0 - p_wv) if pressure_atm != 1.0 else 1.0

    do_sat = c_star_1atm * pressure_correction
    return round(float(do_sat), 3)


def analyze_do_saturation_status(
    temperature: float,
    salinity: float,
    measured_do: float,
) -> Dict[str, Union[float, str]]:
    """
    Phân tích trạng thái bão hòa Oxy của ao nuôi:
    - DO_sat: Nồng độ bão hòa lý thuyết (mg/L).
    - saturation_pct: Tỷ lệ bão hòa thực tế (% Saturation).
    - oxygen_deficit: Mức thiếu hụt oxy (mg/L).
    - status: Phân loại trạng thái sinh học (OVERSATURATED, OPTIMAL, DEFICIT, CRITICAL).
    """
    if measured_do < 0.0:
        raise ValueError(f"measured_do không thể là số âm: {measured_do}")

    do_sat = calculate_do_saturation(temperature, salinity)
    sat_pct = round((measured_do / do_sat) * 100.0, 1)
    deficit = round(do_sat - measured_do, 3)

    if sat_pct > 125.0:
        status = "OVERSATURATED"
        suggestion = "Cảnh báo quá bão hòa do tảo quang hợp mạnh; nguy cơ bệnh bọt khí (Gas Bubble Disease)."
    elif sat_pct >= 85.0:
        status = "OPTIMAL"
        suggestion = "Nồng độ Oxy hòa tan ở mức tối ưu cho tôm bắt mồi và sinh trưởng."
    elif sat_pct >= 60.0:
        status = "DEFICIT"
        suggestion = "Thiếu hụt Oxy nhẹ; cần chuẩn bị quạt nước bổ sung khi trời tắt nắng."
    else:
        status = "CRITICAL"
        suggestion = "Thiếu hụt Oxy nghiêm trọng; nguy cơ tôm nổi đầu ngạt khí! Cần sục khí khẩn cấp."

    return {
        "temperature": temperature,
        "salinity": salinity,
        "measured_do": round(measured_do, 2),
        "do_saturation": do_sat,
        "saturation_percentage": sat_pct,
        "oxygen_deficit": deficit,
        "status": status,
        "action_suggestion": suggestion,
    }


def predict_nighttime_do_depletion(
    current_temp: float,
    salinity: float,
    current_do: float,
    hours_ahead: int = 8,
    aeration_active: bool = False,
    shrimp_density_factor: float = 1.0,
) -> Dict[str, Union[List[Dict], str, float]]:
    """
    Dự báo quỹ đạo suy giảm oxy ban đêm (Nighttime DO Depletion Trajectory).
    
    Cơ chế lý sinh ao tôm:
    - Ban đêm (18:00 - 06:00), quang hợp = 0.
    - Hô hấp tổng thể ao:
      r_resp = (r_shrimp + r_benthos + r_plankton) * Q10^((T - 28)/10)
      Thông thường ở 28-30°C: tốc độ tiêu hao oxy dao động từ 0.28 đến 0.45 mg/L/giờ.
    - Tái cấp oxy qua khuếch tán bề mặt hoặc quạt nước:
      r_reaeration = k_L * (DO_sat - DO)
    """
    do_sat = calculate_do_saturation(current_temp, salinity)

    # Hệ số hô hấp theo nhiệt độ (Q10 = 2.0)
    q10_factor = 2.0 ** ((current_temp - 28.0) / 10.0)
    base_consumption_rate = 0.35 * q10_factor * shrimp_density_factor  # mg/L/giờ

    # Hệ số tái sục khí (quạt nước làm tăng k_L đáng kể)
    k_reaeration = 0.12 if aeration_active else 0.03  # 1/giờ

    trajectory = []
    simulated_do = current_do
    lowest_do = current_do
    lowest_hour = 0

    dt = 1.0  # Bước nhảy 1 giờ
    for h in range(1, hours_ahead + 1):
        # r_in: khuếch tán không khí vào nước
        diff_in = k_reaeration * max(0.0, (do_sat - simulated_do))
        # r_out: tiêu thụ oxy từ hô hấp ao
        net_change = (diff_in - base_consumption_rate) * dt
        simulated_do = max(0.5, simulated_do + net_change)

        if simulated_do < lowest_do:
            lowest_do = simulated_do
            lowest_hour = h

        trajectory.append({
            "hour_step": h,
            "projected_do": round(simulated_do, 2),
            "projected_saturation_pct": round((simulated_do / do_sat) * 100.0, 1),
        })

    # Đánh giá nguy cơ ngạt tôm (Hypoxia Risk)
    if lowest_do < 3.0:
        risk_level = "HIGH"
        alert_msg = (
            f"NGUY CƠ CAO: Dự báo DO sẽ chạm ngưỡng nguy hiểm {lowest_do:.2f} mg/L sau {lowest_hour} giờ! "
            "Cần bật toàn bộ quạt nước phụ và tạt oxy viên khẩn cấp trước 01:00 sáng."
        )
    elif lowest_do < 4.0:
        risk_level = "MEDIUM"
        alert_msg = (
            f"CẢNH BÁO: DO có xu hướng giảm xuống mức {lowest_do:.2f} mg/L. "
            "Khuyến nghị duy trì chạy quạt nước liên tục suốt đêm."
        )
    else:
        risk_level = "LOW"
        alert_msg = f"AN TOÀN: Dự báo DO thấp nhất ở mức an toàn {lowest_do:.2f} mg/L."

    return {
        "initial_do": current_do,
        "do_saturation": do_sat,
        "minimum_projected_do": round(lowest_do, 2),
        "minimum_projected_hour": lowest_hour,
        "risk_level": risk_level,
        "alert_message": alert_msg,
        "trajectory": trajectory,
    }
