"""
Mô hình dự báo quỹ đạo chất lượng nước 12-24h và đánh giá rủi ro dịch bệnh tôm (WSSV, AHPND/EMS).
Tái sử dụng hàm chuẩn nhiệt động học Benson & Krause (1984) từ soft_sensor.py
và động cơ Shrimp WQI đa thông số từ water_quality.py.
"""

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.models.soft_sensor import benson_krause_do_saturation
from app.models.water_quality import calculate_shrimp_wqi

VIETNAM_TZ = timezone(timedelta(hours=7))

# Ngưỡng phân loại rủi ro theo hợp đồng NestJS
TRAJECTORY_RISK_THRESHOLDS: Tuple[float, float] = (35.0, 65.0)
DISEASE_RISK_THRESHOLDS: Tuple[float, float] = (40.0, 70.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _map_risk_level(score: float, warning_min: float, danger_min: float) -> str:
    if score >= danger_min:
        return "DANGER"
    if score >= warning_min:
        return "WARNING"
    return "SAFE"


def _deduplicate_preserve_order(items: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(item for item in items if item))


def _parse_iso_datetime(raw: Any, fallback_tz: Any) -> Optional[datetime]:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=fallback_tz)
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    normalized = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=fallback_tz)


def _extract_attr_or_key(item: Any, *names: str) -> Any:
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return None


def _compute_history_slope(
    base_timestamp: datetime,
    recent_history: Optional[Sequence[Any]],
    current_value: float,
    field_names: Tuple[str, ...],
    max_abs_slope: float,
) -> float:
    """
    Ước lượng tốc độ biến thiên ngắn hạn (°C/h, mg/L/h, pH/h) từ chuỗi lịch sử gần đây
    bằng hồi quy tuyến tính OLS neo tại điểm đo hiện tại (t = 0).
    """
    if not recent_history:
        return 0.0

    points: List[Tuple[float, float]] = []
    for entry in recent_history:
        recorded_raw = _extract_attr_or_key(entry, "recordedAt", "recorded_at")
        val = _extract_attr_or_key(entry, *field_names)
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            continue
        dt = _parse_iso_datetime(recorded_raw, base_timestamp.tzinfo or timezone.utc)
        if dt is None:
            continue
        dt_hours = (dt - base_timestamp).total_seconds() / 3600.0
        # Chỉ dùng dữ liệu trong vòng 24h trước thời điểm dự báo để tránh nhiễu cũ
        if -24.0 <= dt_hours <= -0.05:
            points.append((dt_hours, float(val)))

    if not points:
        return 0.0

    points.sort(key=lambda pair: pair[0])
    points.append((0.0, float(current_value)))

    n = len(points)
    mean_t = sum(t for t, _ in points) / n
    mean_v = sum(v for _, v in points) / n
    denom = sum((t - mean_t) ** 2 for t, _ in points)
    if denom < 1e-6:
        return 0.0

    slope = sum((t - mean_t) * (v - mean_v) for t, v in points) / denom
    return _clamp(slope, -max_abs_slope, max_abs_slope)


def _compute_point_risk(
    do_val: float,
    ph_val: float,
    temp_val: float,
    salinity: float,
    turbidity: float,
    projected_delta_ph: Optional[float] = None,
) -> Tuple[float, Dict[str, Any], List[str], List[str]]:
    """Tính điểm rủi ro chất lượng nước tại một bước thời gian bằng WQI + ngưỡng nguy cấp."""
    do_sat = benson_krause_do_saturation(temp_val, salinity, pressure_atm=1.0)
    wqi_score, _, params_eval, factors, actions = calculate_shrimp_wqi(
        do_mg_l=do_val,
        ph=ph_val,
        temp_c=temp_val,
        salinity_ppt=salinity,
        turbidity_ntu=turbidity,
        delta_ph=projected_delta_ph,
        do_sat_mg_l=do_sat,
    )

    wqi_risk = 100.0 - wqi_score
    statuses = [p.get("status") for p in params_eval.values()]
    max_param_risk = max((float(p.get("risk_score", 0.0)) for p in params_eval.values()), default=0.0)

    is_critical = (
        "DANGER" in statuses
        or do_val < 3.5
        or ph_val < 6.5
        or ph_val > 9.0
        or temp_val < 24.0
        or temp_val > 33.5
    )
    is_warning = "WARNING" in statuses

    if is_critical:
        risk_score = max(wqi_risk, max_param_risk * 0.85, 68.0)
    elif is_warning:
        risk_score = max(wqi_risk, max_param_risk * 0.85, 38.0)
    else:
        risk_score = wqi_risk

    return round(_clamp(risk_score, 0.0, 100.0), 1), params_eval, factors, actions


def forecast_water_quality_trajectory(
    base_timestamp: datetime,
    horizon_hours: int = 24,
    step_hours: int = 1,
    current_do: float = 5.5,
    current_ph: float = 7.8,
    current_temp: float = 28.5,
    salinity: float = 15.0,
    turbidity: float = 25.0,
    recent_history: Optional[Sequence[Any]] = None,
    shrimp_density: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Dự báo quỹ đạo DO, pH, nhiệt độ và điểm rủi ro sinh thái ao tôm trong 12-24 giờ tới.
    Mô phỏng chu kỳ quang hợp/bức xạ mặt trời ban ngày (06:00-18:00 giờ Việt Nam UTC+7),
    hô hấp ban đêm phụ thuộc Q10 và mật độ thả nuôi, trao đổi khí qua bão hòa Benson & Krause,
    kết hợp xu hướng tắt dần từ chuỗi lịch sử gần nhất.
    """
    if base_timestamp.tzinfo is None or base_timestamp.utcoffset() is None:
        raise ValueError("base_timestamp bắt buộc phải có múi giờ (timezone-aware).")
    if not (12 <= horizon_hours <= 24):
        raise ValueError("horizon_hours phải nằm trong khoảng 12..24 giờ.")
    if step_hours not in (1, 2, 3, 4, 6):
        raise ValueError("step_hours chỉ chấp nhận một trong các giá trị: 1, 2, 3, 4, 6.")

    # Xây dựng danh sách các mốc giờ tăng dần, luôn kết thúc đúng tại horizon_hours
    offsets = list(range(step_hours, horizon_hours + 1, step_hours))
    if not offsets or offsets[-1] != horizon_hours:
        offsets.append(horizon_hours)
    offsets_set = set(offsets)

    # Hệ số sinh học theo mật độ tôm (chuẩn 100 con/m² = 1.0) và độ đục/tảo
    density_factor = (
        _clamp(0.65 + 0.35 * (float(shrimp_density) / 100.0), 0.5, 2.2)
        if shrimp_density is not None
        else 1.0
    )
    algae_photo_factor = _clamp(0.5 + 0.5 * min(turbidity, 60.0) / 30.0, 0.4, 1.5)
    organic_resp_factor = 1.0 + max(0.0, turbidity - 40.0) / 120.0

    # Xu hướng ngắn hạn từ recent_history
    do_slope = _compute_history_slope(
        base_timestamp, recent_history, current_do, ("dissolvedOxygen", "dissolved_oxygen"), 0.35
    )
    ph_slope = _compute_history_slope(
        base_timestamp, recent_history, current_ph, ("ph",), 0.12
    )
    temp_slope = _compute_history_slope(
        base_timestamp, recent_history, current_temp, ("temperature",), 0.45
    )

    sim_do = float(current_do)
    sim_ph = float(current_ph)
    sim_temp = float(current_temp)
    ph_values_seen: List[float] = [sim_ph]

    series: List[Dict[str, Any]] = []
    collected_actions: List[str] = []
    peak_risk_point: Optional[Dict[str, Any]] = None
    peak_risk_params: Dict[str, Any] = {}
    min_do_info: Tuple[float, str] = (sim_do, "")

    # Mô phỏng từng bước 1 giờ để quỹ đạo nhất quán bất kể step_hours
    for hour_idx in range(1, horizon_hours + 1):
        target_utc = (base_timestamp + timedelta(hours=hour_idx)).astimezone(timezone.utc)
        local_dt = target_utc.astimezone(VIETNAM_TZ)
        local_hour = local_dt.hour + (local_dt.minute / 60.0) + (local_dt.second / 3600.0)

        # Bức xạ mặt trời / quang hợp (06:00 - 18:00 giờ địa phương UTC+7)
        solar = (
            math.sin(math.pi * (local_hour - 6.0) / 12.0)
            if 6.0 <= local_hour <= 18.0
            else 0.0
        )

        # Hệ số suy giảm xu hướng lịch sử theo thời gian (tau = 6 giờ)
        damping = math.exp(-hour_idx / 6.0)

        # 1. Cập nhật nhiệt độ nước (ấm dần ban ngày, tản nhiệt về đêm)
        temp_delta_h = (0.45 * solar - 0.1432) + (temp_slope * damping)
        sim_temp = _clamp(sim_temp + temp_delta_h, 15.0, 42.0)

        # 2. Tính độ bão hòa DO Benson & Krause (1984) và tốc độ hô hấp Q10
        do_sat = benson_krause_do_saturation(sim_temp, salinity, pressure_atm=1.0)
        q10 = 2.0 ** ((sim_temp - 28.0) / 10.0)

        # Quang hợp giảm dần nếu DO đã siêu bão hòa cao
        sat_attenuation = _clamp(1.4 - 0.3 * (sim_do / max(do_sat, 1e-3)), 0.3, 1.2)
        photo_o2 = 1.00 * solar * algae_photo_factor * sat_attenuation
        resp_o2 = 0.318 * q10 * density_factor * organic_resp_factor
        reaeration = 0.10 * (do_sat - sim_do)

        sim_do = _clamp(
            sim_do + photo_o2 - resp_o2 + reaeration + (do_slope * damping),
            0.5,
            18.0,
        )

        # 3. Cập nhật pH (quang hợp tiêu thụ CO2 làm tăng pH ban ngày, hô hấp làm giảm pH ban đêm)
        photo_ph_up = 0.075 * solar * algae_photo_factor
        resp_ph_down = 0.0239 * q10 * density_factor * organic_resp_factor
        sim_ph = _clamp(
            sim_ph + photo_ph_up - resp_ph_down + (ph_slope * damping),
            5.5,
            10.0,
        )
        ph_values_seen.append(sim_ph)

        if sim_do < min_do_info[0]:
            min_do_info = (sim_do, local_dt.strftime("%H:%M"))

        if hour_idx in offsets_set:
            projected_ph_swing = max(ph_values_seen) - min(ph_values_seen)
            pt_risk, params_eval, _, pt_actions = _compute_point_risk(
                do_val=sim_do,
                ph_val=sim_ph,
                temp_val=sim_temp,
                salinity=salinity,
                turbidity=turbidity,
                projected_delta_ph=projected_ph_swing if projected_ph_swing > 0.5 else None,
            )
            pt_level = _map_risk_level(pt_risk, *TRAJECTORY_RISK_THRESHOLDS)
            point_dict = {
                "offsetHours": hour_idx,
                "predictedTime": target_utc.isoformat(),
                "predictedDO": round(sim_do, 2),
                "predictedPH": round(sim_ph, 2),
                "predictedTemperature": round(sim_temp, 2),
                "riskScore": pt_risk,
                "riskLevel": pt_level,
            }
            series.append(point_dict)
            collected_actions.extend(pt_actions)

            if peak_risk_point is None or pt_risk > peak_risk_point["riskScore"]:
                peak_risk_point = point_dict
                peak_risk_params = params_eval

    overall_risk_score = round(max((pt["riskScore"] for pt in series), default=0.0), 1)
    overall_risk_level = _map_risk_level(overall_risk_score, *TRAJECTORY_RISK_THRESHOLDS)

    # Tổng hợp nhân tố rủi ro và khuyến nghị tiếng Việt không trùng lặp
    factors: List[str] = []
    for param_data in peak_risk_params.values():
        if param_data.get("status") in ("WARNING", "DANGER") and param_data.get("message"):
            factors.append(param_data["message"])

    if min_do_info[0] < 3.5 and min_do_info[1]:
        factors.append(
            f"Dự báo Oxy hòa tan có thể tụt xuống mức thấp {min_do_info[0]:.2f} mg/L vào lúc {min_do_info[1]} (giờ Việt Nam)."
        )
        collected_actions.append(
            "Lên lịch bật toàn bộ quạt nước và sục khí đáy trong khung giờ ban đêm đến sáng sớm."
        )
    elif min_do_info[0] < 4.5 and min_do_info[1]:
        factors.append(
            f"Oxy hòa tan dự kiến giảm về {min_do_info[0]:.2f} mg/L vào khoảng {min_do_info[1]} do hô hấp ban đêm."
        )

    projected_ph_swing = max(ph_values_seen) - min(ph_values_seen)
    if projected_ph_swing > 0.5:
        factors.append(
            f"Biên độ dao động pH dự kiến {projected_ph_swing:.2f} (> 0.5) trong chu kỳ dự báo."
        )
        collected_actions.append(
            "Kiểm tra độ kiềm (duy trì 120-160 mg CaCO3/L) để ổn định hệ đệm pH ngày/đêm."
        )

    if shrimp_density is not None and shrimp_density > 150.0:
        factors.append(
            f"Mật độ nuôi cao ({shrimp_density:.0f} con/m²) làm tăng tốc độ tiêu thụ oxy ban đêm."
        )
        collected_actions.append(
            "Duy trì vận hành quạt nước liên tục và kiểm soát chặt khẩu phần ăn ở ao mật độ cao."
        )

    if do_slope <= -0.15:
        factors.append(
            "Chuỗi lịch sử gần đây cho thấy xu hướng suy giảm Oxy hòa tan đang tiếp diễn."
        )

    if not factors:
        factors.append(
            "Quỹ đạo chất lượng nước trong 12-24h tới ổn định và đạt chuẩn QCVN 02-19:2014."
        )

    recommendations = _deduplicate_preserve_order(collected_actions)
    if not recommendations:
        recommendations.append(
            "Duy trì chế độ sục khí hiện tại và theo dõi định kỳ các chỉ số DO, pH, nhiệt độ."
        )

    return {
        "overallRiskScore": overall_risk_score,
        "overallRiskLevel": overall_risk_level,
        "series": series,
        "factors": _deduplicate_preserve_order(factors),
        "recommendations": recommendations,
    }


def _evaluate_wssv_risk(
    current_do: float,
    current_ph: float,
    current_temp: float,
    salinity: float,
    temperature_delta: Optional[float],
    ph_delta: Optional[float],
    min_do: Optional[float],
    min_temp: Optional[float],
    max_temp: Optional[float],
    shrimp_density: Optional[float],
) -> Dict[str, Any]:
    """Đánh giá nguy cơ bùng phát Bệnh Đốm trắng (WSSV)."""
    score = 5.0
    indicators: List[str] = []
    recommendations: List[str] = []

    # 1. Nước lạnh (< 27°C, nặng < 25°C) - điều kiện thuận lợi cho virus WSSV nhân lên
    if current_temp < 25.0:
        score += 32.0
        indicators.append(
            f"Nhiệt độ nước lạnh sâu ({current_temp:.1f}°C < 25°C), kích hoạt mạnh nguy cơ bùng phát WSSV."
        )
        recommendations.append(
            "Duy trì mực nước ao sâu (>= 1.5m) để giữ nhiệt, giảm 30-50% lượng thức ăn và bổ sung Vitamin C/beta-glucan."
        )
    elif current_temp < 27.0:
        score += 25.0
        indicators.append(
            f"Nhiệt độ nước thấp ({current_temp:.1f}°C < 27°C), làm giảm miễn dịch tôm nuôi."
        )
        recommendations.append(
            "Giảm 15-25% khẩu phần ăn vào thời điểm nước mát và tăng cường khoáng chất tăng đề kháng."
        )
    elif min_temp is not None and min_temp < 25.0:
        score += 18.0
        indicators.append(
            f"Nhiệt độ thấp nhất 24h qua từng xuống {min_temp:.1f}°C (< 25°C), gây stress lạnh cho tôm."
        )
        recommendations.append("Theo dõi sát nhiệt độ vào rạng sáng và giữ mực nước ổn định.")

    # 2. Sốc nhiệt 24h (temperatureDelta >= 3.0°C)
    effective_temp_delta = temperature_delta
    if effective_temp_delta is None and min_temp is not None and max_temp is not None:
        effective_temp_delta = max(0.0, max_temp - min_temp)
    if effective_temp_delta is not None and effective_temp_delta >= 3.0:
        score += 26.0
        indicators.append(
            f"Sốc nhiệt 24h lớn (ΔT = {effective_temp_delta:.1f}°C >= 3.0°C), dễ kích hoạt virus WSSV tiềm ẩn."
        )
        recommendations.append(
            "Tạt khoáng chống sốc và Vitamin C sau biến động nhiệt/mưa lớn; hạn chế thay nước đột ngột."
        )

    # 3. Dao động pH lớn (> 0.5) hoặc pH cực đoan (< 7.0 hoặc > 9.0)
    if ph_delta is not None and ph_delta > 0.5:
        score += 18.0 if ph_delta <= 1.0 else 22.0
        indicators.append(
            f"Biến động pH 24h vượt ngưỡng an toàn (ΔpH = {ph_delta:.2f} > 0.5), gây stress khi tôm lột xác."
        )
        recommendations.append(
            "Nâng độ kiềm bằng Dolomite/CaCO3 để giảm biên độ dao động pH ngày và đêm."
        )

    if current_ph < 7.0 or current_ph > 9.0:
        score += 18.0
        indicators.append(
            f"Độ pH ngoài vùng chuẩn QCVN (pH = {current_ph:.2f}, ngưỡng an toàn 7.0 - 9.0)."
        )
        recommendations.append(
            "Điều chỉnh pH về ngưỡng 7.5 - 8.5 bằng vôi CaCO3 (nếu pH thấp) hoặc mật rỉ đường + vi sinh (nếu pH cao)."
        )

    # 4. Độ mặn thấp (< 5 ppt)
    if salinity < 5.0:
        score += 16.0 if salinity < 3.0 else 12.0
        indicators.append(
            f"Độ mặn thấp ({salinity:.1f} ppt < 5 ppt), làm suy yếu áp suất thẩm thấu và vỏ tôm."
        )
        recommendations.append(
            "Bổ sung khoáng vi lượng (Ca2+, Mg2+, K+) định kỳ để hỗ trợ tôm cứng vỏ nhanh."
        )

    # 5. Oxy hòa tan thấp (< 4.0 hoặc minDO < 3.5)
    if current_do < 3.5 or (min_do is not None and min_do < 3.5):
        score += 18.0
        low_do_val = min(current_do, min_do) if min_do is not None else current_do
        indicators.append(
            f"Oxy hòa tan chạm ngưỡng thiếu oxy (DO = {low_do_val:.2f} mg/L < 3.5 mg/L), làm tôm suy kiệt."
        )
        recommendations.append(
            "Tăng cường chạy toàn bộ quạt nước và sục khí đáy, kiểm tra lại mật độ tảo."
        )
    elif current_do < 4.0:
        score += 12.0
        indicators.append(
            f"Oxy hòa tan thấp ({current_do:.2f} mg/L < 4.0 mg/L), tăng stress hô hấp."
        )
        recommendations.append("Bật thêm quạt nước để duy trì DO >= 5.0 mg/L.")

    # 6. Mật độ nuôi cao (> 150 con/m²)
    if shrimp_density is not None and shrimp_density > 150.0:
        score += 14.0
        indicators.append(
            f"Mật độ thả nuôi cao ({shrimp_density:.0f} con/m² > 150 con/m²), tăng nguy cơ lây lan nhanh WSSV."
        )
        recommendations.append(
            "Xi-phông đáy thường xuyên, kiểm soát chất lượng nước và áp dụng an toàn sinh học nghiêm ngặt."
        )

    risk_score = round(_clamp(score, 5.0, 100.0), 1)
    risk_level = _map_risk_level(risk_score, *DISEASE_RISK_THRESHOLDS)

    if not indicators:
        indicators.append(
            "Chưa ghi nhận các yếu tố môi trường kích hoạt nguy cơ bệnh Đốm trắng (WSSV)."
        )

    dedup_recs = _deduplicate_preserve_order(recommendations)
    if not dedup_recs:
        dedup_recs.append(
            "Duy trì an toàn sinh học ao nuôi, ổn định nhiệt độ và pH hàng ngày."
        )

    return {
        "code": "WSSV",
        "name": "Bệnh Đốm trắng (WSSV)",
        "riskScore": risk_score,
        "riskLevel": risk_level,
        "indicators": indicators,
        "recommendations": dedup_recs,
    }


def _evaluate_ahpnd_risk(
    current_do: float,
    current_ph: float,
    current_temp: float,
    salinity: float,
    turbidity: float,
    nh3: Optional[float],
    no2: Optional[float],
    min_do: Optional[float],
    max_temp: Optional[float],
    days_of_culture: Optional[int],
) -> Dict[str, Any]:
    """Đánh giá nguy cơ Bệnh Hoại tử gan tụy cấp (AHPND/EMS)."""
    score = 5.0
    indicators: List[str] = []
    recommendations: List[str] = []

    # 1. Nước ấm (> 31°C, nặng > 33°C) thúc đẩy vi khuẩn Vibrio parahaemolyticus
    if current_temp > 33.0:
        score += 24.0
        indicators.append(
            f"Nhiệt độ nước cao ({current_temp:.1f}°C > 33°C), tạo điều kiện thuận lợi cho vi khuẩn Vibrio gây AHPND/EMS."
        )
        recommendations.append(
            "Nâng mực nước ao (> 1.4m), chạy quạt chống phân tầng nhiệt và giảm 15-20% thức ăn lúc nắng gắt."
        )
    elif current_temp > 31.0:
        score += 16.0
        indicators.append(
            f"Nhiệt độ nước ấm ({current_temp:.1f}°C > 31°C), gia tăng mật số vi khuẩn Vibrio trong ao."
        )
        recommendations.append(
            "Kiểm tra mật độ khuẩn Vibrio định kỳ và bổ sung men vi sinh đối kháng (Bacillus spp.)."
        )
    elif max_temp is not None and max_temp > 33.0:
        score += 10.0
        indicators.append(
            f"Nhiệt độ đỉnh 24h qua đạt {max_temp:.1f}°C (> 33°C), làm tăng nguy cơ phát triển Vibrio."
        )

    # 2. Độ mặn cao (> 20 ppt, nặng > 25 ppt)
    if salinity > 25.0:
        score += 20.0
        indicators.append(
            f"Độ mặn cao ({salinity:.1f} ppt > 25 ppt), thuận lợi cho chủng Vibrio parahaemolyticus phát triển mạnh."
        )
        recommendations.append(
            "Cấp bổ sung nước ngọt đã qua xử lý để hạ dần độ mặn nếu có điều kiện, đồng thời tăng vi sinh có lợi."
        )
    elif salinity > 20.0:
        score += 13.0
        indicators.append(
            f"Độ mặn tương đối cao ({salinity:.1f} ppt > 20 ppt), làm tăng nguy cơ nhiễm khuẩn gan tụy."
        )

    # 3. pH kiềm (> 8.3)
    if current_ph > 8.3:
        score += 20.0 if current_ph > 8.8 else 14.0
        indicators.append(
            f"Môi trường nước kiềm (pH = {current_ph:.2f} > 8.3), làm tăng độc lực Vibrio và khí độc NH3."
        )
        recommendations.append(
            "Đánh mật rỉ đường kết hợp vi sinh vào buổi sáng để kiểm soát pH xuống khoảng 7.6 - 8.2."
        )

    # 4. Khí độc NH3 (> 0.05 nặng / > 0.02 trung bình) và NO2 (> 5.0 / > 1.0)
    if nh3 is not None:
        if nh3 > 0.05:
            score += 22.0
            indicators.append(
                f"Khí độc NH3 ở mức nguy hiểm ({nh3:.3f} mg/L > 0.05 mg/L), làm tổn thương mang và suy gan tụy."
            )
            recommendations.append(
                "Cắt giảm cữ ăn, thay nước sạch hoặc đánh Yucca/vi sinh hấp thu khí độc NH3 khẩn cấp."
            )
        elif nh3 > 0.02:
            score += 14.0
            indicators.append(
                f"Khí độc NH3 vượt ngưỡng an toàn ({nh3:.3f} mg/L > 0.02 mg/L)."
            )
            recommendations.append(
                "Tăng cường sục khí, giảm thức ăn dư thừa và bổ sung men vi sinh xử lý đáy ao."
            )

    if no2 is not None:
        if no2 > 5.0:
            score += 16.0
            indicators.append(
                f"Nồng độ Nitrite cao ({no2:.2f} mg/L > 5.0 mg/L), làm tôm giảm miễn dịch với vi khuẩn."
            )
            recommendations.append(
                "Xi-phông đáy ao loại bỏ chất hữu cơ và bổ sung vi khuẩn chuyển hóa Nitrite (Nitrospira/Nitrobacter)."
            )
        elif no2 > 1.0:
            score += 10.0
            indicators.append(
                f"Nồng độ Nitrite có dấu hiệu tăng ({no2:.2f} mg/L > 1.0 mg/L)."
            )

    # 5. Độ đục cao (> 60 NTU) phản ánh chất hữu cơ lơ lửng / tảo tàn
    if turbidity > 60.0:
        score += 14.0 if turbidity > 80.0 else 10.0
        indicators.append(
            f"Độ đục nước cao ({turbidity:.1f} NTU > 60 NTU), tích tụ nhiều chất lơ lửng và mầm bệnh cơ hội."
        )
        recommendations.append(
            "Tăng chạy quạt gom tụ chất thải, xi-phông đáy và dùng vi sinh phân hủy bùn bã hữu cơ."
        )

    # 6. Oxy hòa tan thấp (< 4.0 hoặc minDO < 3.5)
    if current_do < 3.5 or (min_do is not None and min_do < 3.5):
        score += 16.0
        low_do_val = min(current_do, min_do) if min_do is not None else current_do
        indicators.append(
            f"Thiếu oxy hòa tan (DO = {low_do_val:.2f} mg/L < 3.5 mg/L) làm giảm sức đề kháng gan tụy."
        )
        recommendations.append(
            "Bật tối đa quạt nước và sục khí đáy để giữ DO ổn định >= 5.0 mg/L."
        )
    elif current_do < 4.0:
        score += 10.0
        indicators.append(
            f"Oxy hòa tan dưới mức khuyến nghị ({current_do:.2f} mg/L < 4.0 mg/L)."
        )

    # 7. Giai đoạn nhạy cảm 10..45 ngày tuổi (daysOfCulture)
    if days_of_culture is not None and 10 <= days_of_culture <= 45:
        score += 14.0
        indicators.append(
            f"Đàn tôm đang trong giai đoạn nhạy cảm cao với AHPND/EMS ({days_of_culture} ngày tuổi, cửa sổ 10-45 ngày)."
        )
        recommendations.append(
            "Trộn bổ sung men tiêu hóa, axit hữu cơ và thảo dược bảo vệ gan tụy trong giai đoạn 10-45 ngày nuôi."
        )

    risk_score = round(_clamp(score, 5.0, 100.0), 1)
    risk_level = _map_risk_level(risk_score, *DISEASE_RISK_THRESHOLDS)

    if not indicators:
        indicators.append(
            "Chưa ghi nhận các yếu tố môi trường thuận lợi cho bệnh Hoại tử gan tụy cấp (AHPND/EMS)."
        )

    dedup_recs = _deduplicate_preserve_order(recommendations)
    if not dedup_recs:
        dedup_recs.append(
            "Duy trì quản lý thức ăn chặt chẽ, định kỳ kiểm tra gan tụy và mật độ khuẩn Vibrio."
        )

    return {
        "code": "AHPND_EMS",
        "name": "Bệnh Hoại tử gan tụy cấp (AHPND/EMS)",
        "riskScore": risk_score,
        "riskLevel": risk_level,
        "indicators": indicators,
        "recommendations": dedup_recs,
    }


def assess_disease_risk(
    current_do: float,
    current_ph: float,
    current_temp: float,
    salinity: float = 15.0,
    turbidity: float = 25.0,
    nh3: Optional[float] = None,
    no2: Optional[float] = None,
    temperature_delta: Optional[float] = None,
    ph_delta: Optional[float] = None,
    min_do: Optional[float] = None,
    min_temp: Optional[float] = None,
    max_temp: Optional[float] = None,
    shrimp_density: Optional[float] = None,
    days_of_culture: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Đánh giá tổng hợp rủi ro bùng phát dịch bệnh tôm (WSSV và AHPND/EMS)
    dựa trên các thông số lý hóa hiện tại, biến động 24h và hồ sơ ao nuôi.
    """
    wssv = _evaluate_wssv_risk(
        current_do=current_do,
        current_ph=current_ph,
        current_temp=current_temp,
        salinity=salinity,
        temperature_delta=temperature_delta,
        ph_delta=ph_delta,
        min_do=min_do,
        min_temp=min_temp,
        max_temp=max_temp,
        shrimp_density=shrimp_density,
    )
    ahpnd = _evaluate_ahpnd_risk(
        current_do=current_do,
        current_ph=current_ph,
        current_temp=current_temp,
        salinity=salinity,
        turbidity=turbidity,
        nh3=nh3,
        no2=no2,
        min_do=min_do,
        max_temp=max_temp,
        days_of_culture=days_of_culture,
    )

    overall_risk_score = round(max(wssv["riskScore"], ahpnd["riskScore"]), 1)
    overall_risk_level = _map_risk_level(overall_risk_score, *DISEASE_RISK_THRESHOLDS)

    # Kết hợp khuyến nghị từ các bệnh có cảnh báo/nguy hiểm trước; nếu đều SAFE thì gộp chung
    elevated_recs: List[str] = []
    for disease in (wssv, ahpnd):
        if disease["riskLevel"] in ("WARNING", "DANGER"):
            elevated_recs.extend(disease["recommendations"])

    if elevated_recs:
        combined_recommendations = _deduplicate_preserve_order(elevated_recs)
    else:
        combined_recommendations = _deduplicate_preserve_order(
            wssv["recommendations"] + ahpnd["recommendations"]
        )

    return {
        "overallRiskScore": overall_risk_score,
        "overallRiskLevel": overall_risk_level,
        "diseases": [wssv, ahpnd],
        "recommendations": combined_recommendations,
    }
