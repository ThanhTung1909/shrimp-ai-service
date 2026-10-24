"""
Động cơ Đánh giá & Phân tích Chất lượng Nước Đa Thông số Nuôi Tôm (Aquaculture Water Quality Engine)
Căn cứ khoa học 100% dựa trên các công trình nghiên cứu thực nghiệm đã công bố:
1. Đỗ Doãn Dung, Nguyễn Nhất Tuấn, Lê Hùng Anh, Đỗ Phương Khanh (2025).
   "Ứng dụng nền tảng IoT vào tự động hóa trong nuôi tôm tại Việt Nam",
   Tạp chí Khoa học Đại học Mở Hà Nội, DOI: 10.59266/houjs.2025.844. (Thực nghiệm tại Minh Phú - Lộc An)
2. Nguyễn Hữu Nghĩa, Nguyễn Đức Bình, Phạm Thái Giang et al. (2022).
   "Nghiên cứu chất lượng nước và bệnh trong nuôi tôm thẻ chân trắng (Penaeus vannamei) áp dụng công nghệ Nanobubble",
   Tạp chí Khoa học & Công nghệ Việt Nam, 64(5), tr. 58-64, DOI: 10.31276/VJST.64(5).58-64. (RIA1)
3. Ngô Thụy Diễm Trang, Trần Đình Duy, Trịnh Phước Toàn et al. (2022).
   "Đánh giá chất lượng nước và thải lượng từ ao nuôi tôm thẻ chân trắng (Litopenaeus vannamei) thâm canh ở tỉnh Sóc Trăng",
   Tạp chí Khoa học Trường Đại học Cần Thơ, Tập 58, Số 1B, tr. 213-225, DOI: 10.22144/ctu.jvn.2022.024.
4. Quy chuẩn Kỹ thuật Quốc gia: QCVN 02-19:2014/BNNPTNT về cơ sở nuôi tôm nước lợ.
5. Cân bằng nhiệt động học Albert (1973) & Emerson et al. (1975) cho khí độc Amoniac (NH3).
6. Phân tầng động học độc tính Nitrite theo độ mặn của Lin & Chen (2003) và Samocha (2019).
7. Ngưỡng bão hòa và nguy cơ bóng khí của C.E. Boyd & Fast (1992) và Weitkamp et al. (1980).
"""

import math
from typing import Any, Dict, List, Optional, Tuple


def calculate_toxic_ammonia_nh3(
    tan_mg_l: float,
    temperature_c: float,
    ph: float,
    salinity_ppt: float = 15.0,
) -> float:
    """
    Tính nồng độ Amoniac tự do độc tính cao (NH3-N, mg/L) từ Tổng Amoniac (TAN).
    Áp dụng phương trình nhiệt động học chuẩn của Albert (1973) và Emerson et al. (1975).
    
    Căn cứ khoa học:
    - Albert, A. (1973). Selective Toxicity.
    - Emerson, K. et al. (1975). "Aqueous ammonia equilibrium calculations".
    - Nguyễn Hữu Nghĩa et al. (2022): NH3 trung bình 0.019 - 0.026 mg/L; NH3 > 0.05 mg/L gây hoại tử tế bào mang.
    """
    if tan_mg_l <= 0.0:
        return 0.0

    t_kelvin = temperature_c + 273.15
    # Lực ion ước lượng từ độ mặn (Ionic strength I)
    ionic_strength = 0.0199 * salinity_ppt

    # Hằng số điện ly pKa hiệu chỉnh theo nhiệt độ và độ mặn
    pka = 0.09018 + (2729.92 / t_kelvin) + (0.1552 - 0.000314 * temperature_c) * ionic_strength

    # Tỷ lệ phân ly của NH3 không ion hóa
    f_nh3 = 1.0 / (math.pow(10.0, pka - ph) + 1.0)
    toxic_nh3 = tan_mg_l * f_nh3
    return round(toxic_nh3, 4)


def evaluate_dissolved_oxygen(
    do_mg_l: float,
    do_saturation_mg_l: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Đánh giá Oxy hòa tan và rủi ro ngạt khí / siêu bão hòa khí.
    
    Căn cứ khoa học:
    - QCVN 02-19:2014/BNNPTNT: DO >= 3.5 mg/L.
    - Nguyễn Hữu Nghĩa et al. (2022): DO duy trì trên 5.0 mg/L cho tôm phát triển tối ưu.
    - C.E. Boyd & Fast (1992); Weitkamp et al. (1980): DO > 20 mg/L hoặc độ bão hòa > 300% 
      gây chấn thương bóng khí (Gas Bubble Trauma) làm tắc mạch máu và tử vong tôm.
    """
    risk_score = 0.0
    status = "OPTIMAL"
    message = "Oxy hòa tan dồi dào, tôm hô hấp thuận lợi."
    action = None

    sat_pct = (do_mg_l / do_saturation_mg_l * 100.0) if do_saturation_mg_l and do_saturation_mg_l > 0 else None

    # Kiểm tra siêu bão hòa (Boyd & Fast 1992, Weitkamp 1980)
    if do_mg_l > 20.0 or (sat_pct is not None and sat_pct > 300.0):
        status = "DANGER"
        risk_score = 95.0
        message = f"NGUY HIỂM: Oxy siêu bão hòa ({do_mg_l:.2f} mg/L, >300%), nguy cơ chấn thương bóng khí gây tắc mạch mang tôm (Boyd & Fast, 1992)!"
        action = "Tắt bớt thiết bị sục khí/oxy nguyên chất, khuấy đảo mặt nước để thoát khí thừa."
    elif do_mg_l > 12.0 or (sat_pct is not None and sat_pct > 150.0):
        status = "WARNING"
        risk_score = 45.0
        message = f"CẢNH BÁO: Nước quá bão hòa oxy ({do_mg_l:.2f} mg/L), tảo đang nở hoa quang hợp mạnh."
        action = "Kiểm tra mật độ tảo, chuẩn bị phương án quạt nước ban đêm khi tảo ngừng quang hợp."
    elif do_mg_l < 3.0:
        status = "DANGER"
        risk_score = 95.0
        message = f"NGUY CẤP: Oxy hòa tan sụt giảm nghiêm trọng ({do_mg_l:.2f} mg/L < 3.0 mg/L), tôm có nguy cơ ngạt và chết tầng đáy!"
        action = "BẬT TOÀN BỘ QUẠT NƯỚC VÀ SỤC KHÍ CẤP TỐC; rải oxy viên khẩn cấp quanh ao."
    elif do_mg_l < 3.5:
        status = "DANGER"
        risk_score = 80.0
        message = f"NGUY HIỂM: DO ({do_mg_l:.2f} mg/L) dưới ngưỡng quy chuẩn quốc gia QCVN 02-19:2014 (DO >= 3.5 mg/L)."
        action = "Bật quạt nước, tạm dừng cho ăn cữ tiếp theo để giảm tiêu thụ oxy."
    elif do_mg_l < 4.5:
        status = "WARNING"
        risk_score = 40.0
        message = f"CẢNH BÁO: Oxy hòa tan ở mức thấp ({do_mg_l:.2f} mg/L), tôm giảm chuyển hóa thức ăn."
        action = "Bật thêm quạt nước tăng cường hàm lượng oxy."
    elif do_mg_l <= 8.5:
        status = "OPTIMAL"
        risk_score = 0.0
        message = f"Oxy hòa tan tối ưu ({do_mg_l:.2f} mg/L) theo tiêu chuẩn nuôi tôm công nghiệp."
    else:
        status = "ACCEPTABLE"
        risk_score = 10.0
        message = f"Oxy hòa tan mức cao ({do_mg_l:.2f} mg/L), an toàn cho đàn tôm."

    return {
        "value": round(do_mg_l, 2),
        "saturation_pct": round(sat_pct, 1) if sat_pct is not None else None,
        "status": status,
        "risk_score": risk_score,
        "message": message,
        "action": action,
    }


def evaluate_ph(ph: float, delta_ph_day_night: Optional[float] = None) -> Dict[str, Any]:
    """
    Đánh giá độ pH và biên độ dao động pH ngày/đêm.
    
    Căn cứ khoa học:
    - QCVN 02-19:2014/BNNPTNT: pH từ 7.0 đến 9.0.
    - Ngô Thụy Diễm Trang et al. (2022); Chamberlain (1988): pH tối ưu 7.5 - 8.5; 
      dao động ngày/đêm Delta pH <= 0.5. Cuối vụ nuôi mật độ cao pH thường giảm < 7.0 gây hại tôm.
    - Mưa làm giảm pH đột ngột.
    """
    risk_score = 0.0
    status = "OPTIMAL"
    message = "Độ pH ổn định trong khoảng lý tưởng."
    action = None

    if ph < 6.5:
        status = "DANGER"
        risk_score = 90.0
        message = f"NGUY HIỂM: Nước bị axit hóa nghiêm trọng (pH = {ph:.2f} < 6.5), tôm mềm vỏ, chậm lột xác, khí độc H2S tăng độc tính!"
        action = "Tạt vôi canxi nông nghiệp (CaCO3 hoặc CaO liều 15-20 kg/1000m3) để nâng pH khẩn cấp."
    elif ph < 7.0:
        status = "WARNING"
        risk_score = 55.0
        message = f"CẢNH BÁO: Độ pH = {ph:.2f} dưới ngưỡng tối ưu QCVN 02-19:2014 (7.0 - 9.0)."
        action = "Bổ sung vôi Dolomite hoặc CaCO3 để duy trì đệm kiềm và nâng pH lên >= 7.5."
    elif ph > 9.0:
        status = "DANGER"
        risk_score = 85.0
        message = f"NGUY HIỂM: Độ pH kiềm hóa quá cao (pH = {ph:.2f} > 9.0), độc tính khí Amoniac (NH3) tăng vọt làm mòn mang tôm!"
        action = "Đánh mật rỉ đường (3-5 kg/1000m3) hoặc tạt vi sinh EM lúc 8-9h sáng để giảm bớt pH."
    elif ph > 8.5:
        status = "WARNING"
        risk_score = 45.0
        message = f"CẢNH BÁO: Độ pH = {ph:.2f} tiệm cận ngưỡng kiềm cao, làm tăng độc tính NH3 tự do."
        action = "Hạn chế bón vôi; theo dõi mật độ tảo."
    else:
        status = "OPTIMAL"
        risk_score = 0.0
        message = f"Độ pH = {ph:.2f} đạt chuẩn lý tưởng cho tôm thẻ chân trắng (7.5 - 8.5)."

    # Kiểm tra biến thiên ngày đêm nếu có
    if delta_ph_day_night is not None:
        if delta_ph_day_night > 1.0:
            risk_score = max(risk_score, 80.0)
            status = "DANGER"
            message += f" [CẢNH BÁO KÉP: Biên độ dao động ngày/đêm quá lớn Delta_pH = {delta_ph_day_night:.2f} > 1.0 báo hiệu tảo nở hoa quá mức!]"
            action = "Cắt giảm thức ăn, thay nước hoặc xử lý bớt mật độ tảo."
        elif delta_ph_day_night > 0.5:
            risk_score = max(risk_score, 40.0)
            if status == "OPTIMAL":
                status = "WARNING"
            message += f" [Lưu ý: Dao động Delta_pH = {delta_ph_day_night:.2f} > 0.5 vượt khuyến nghị Ngô Thụy Diễm Trang et al. 2022]."

    return {
        "value": round(ph, 2),
        "status": status,
        "risk_score": risk_score,
        "message": message,
        "action": action,
    }


def evaluate_temperature(
    temp_c: float,
    delta_temp_rain: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Đánh giá nhiệt độ nước ao nuôi và cảnh báo sốc nhiệt sau mưa.
    
    Căn cứ khoa học:
    - QCVN 02-19:2014/BNNPTNT: Nhiệt độ 18 - 33°C.
    - Ngô Thụy Diễm Trang et al. (2022): Khoảng tối ưu cho sinh trưởng tôm là 28.0 - 32.3°C.
    - Đỗ Doãn Dung et al. (2025): Mưa làm giảm nhiệt độ nước ao từ 3 đến 5°C,
      khiến sức ăn của tôm giảm ít nhất 30% so với thông thường.
    """
    risk_score = 0.0
    status = "OPTIMAL"
    message = "Nhiệt độ nước tối ưu cho tôm trao đổi chất."
    action = None

    if temp_c > 33.5:
        status = "DANGER"
        risk_score = 75.0
        message = f"NGUY HIỂM: Nhiệt độ nước quá cao ({temp_c:.1f}°C > 33.5°C), gia tăng nguy cơ bùng phát khuẩn Vibrio và cạn kiệt oxy!"
        action = "Nâng cao mực nước ao (>1.4m), chạy quạt nước chống phân tầng nhiệt."
    elif temp_c > 32.0:
        status = "WARNING"
        risk_score = 35.0
        message = f"CẢNH BÁO: Nhiệt độ nước cao ({temp_c:.1f}°C), tôm tăng tốc độ hô hấp và tiêu hao oxy."
    elif temp_c < 24.0:
        status = "DANGER"
        risk_score = 80.0
        message = f"NGUY HIỂM: Nước lạnh ({temp_c:.1f}°C < 24°C), tôm giảm trao đổi chất nghiêm trọng, dễ nhiễm bệnh."
        action = "Giảm mạnh lượng thức ăn, giữ mực nước sâu ổn định nhiệt độ."
    elif temp_c < 26.0:
        status = "WARNING"
        risk_score = 45.0
        message = f"CẢNH BÁO: Nước mát ({temp_c:.1f}°C), sức ăn của đàn tôm chậm lại."
        action = "Cắt giảm 15 - 20% lượng thức ăn cữ này."
    else:
        status = "OPTIMAL"
        risk_score = 0.0
        message = f"Nhiệt độ nước ({temp_c:.1f}°C) trong khoảng sinh trưởng tối ưu (28 - 32°C)."

    # Phát hiện hiện tượng mưa gây sụt nhiệt độ (Đỗ Doãn Dung et al., 2025)
    if delta_temp_rain is not None and delta_temp_rain <= -3.0:
        status = "DANGER"
        risk_score = max(risk_score, 85.0)
        message += f" [CẢNH BÁO SỐC NƯỚC MƯA: Nhiệt độ tụt dốc {abs(delta_temp_rain):.1f}°C do mưa (Đỗ Doãn Dung et al., 2025), sức ăn của tôm giảm ít nhất 30%!]"
        action = "Cắt giảm ngay 30 - 50% lượng thức ăn cữ sáng; rải vôi quanh bờ ao chống tụt pH."

    return {
        "value": round(temp_c, 1),
        "status": status,
        "risk_score": risk_score,
        "message": message,
        "action": action,
    }


def evaluate_salinity(salinity_ppt: float) -> Dict[str, Any]:
    """
    Đánh giá độ mặn và áp suất thẩm thấu.
    
    Căn cứ khoa học:
    - QCVN 02-19:2014/BNNPTNT: Độ mặn 5 - 35 ppt.
    - Kungvankij et al. (1986); Wanninayake et al. (2001); Sơn et al. (2014): 
      Độ mặn tốt nhất để tôm tăng trưởng nhanh là từ 10 - 30 ppt.
    - Zhang et al. (2009): Ở độ mặn 5 ppt tôm chỉ có tỷ lệ sống 12.5% sau 96 giờ.
    """
    risk_score = 0.0
    status = "OPTIMAL"
    message = "Độ mặn thích hợp cho tôm sinh trưởng."
    action = None

    if salinity_ppt < 3.0:
        status = "DANGER"
        risk_score = 90.0
        message = f"NGUY HIỂM: Độ mặn quá thấp ({salinity_ppt:.1f} ppt < 3 ppt), tôm bị rối loạn áp suất thẩm thấu, nguy cơ tử vong cao (Zhang et al. 2009)!"
        action = "Bổ sung khoáng vi lượng, tăng cường hàm lượng ion Ca2+, Mg2+, K+ khẩn cấp."
    elif salinity_ppt < 5.0:
        status = "WARNING"
        risk_score = 60.0
        message = f"CẢNH BÁO: Độ mặn thấp ({salinity_ppt:.1f} ppt) dưới ngưỡng quy chuẩn QCVN 02-19:2014 (5 - 35 ppt)."
        action = "Tạt khoáng tạt định kỳ, kiểm tra độ cứng của vỏ tôm."
    elif salinity_ppt > 35.0:
        status = "DANGER"
        risk_score = 75.0
        message = f"CẢNH BÁO: Độ mặn cao ({salinity_ppt:.1f} ppt > 35 ppt), tôm chậm lớn, tiêu tốn nhiều năng lượng điều hòa thẩm thấu."
        action = "Cấp bổ sung nước ngọt lắng sạch để hạ dần độ mặn."
    elif salinity_ppt > 30.0:
        status = "ACCEPTABLE"
        risk_score = 20.0
        message = f"Độ mặn cao ({salinity_ppt:.1f} ppt), cần kiểm soát độ bốc hơi nước."
    elif salinity_ppt >= 10.0:
        status = "OPTIMAL"
        risk_score = 0.0
        message = f"Độ mặn ({salinity_ppt:.1f} ppt) trong khoảng tăng trưởng nhanh nhất (10 - 25 ppt)."
    else:
        status = "ACCEPTABLE"
        risk_score = 15.0
        message = f"Độ mặn ({salinity_ppt:.1f} ppt) chấp nhận được, cần bổ sung khoáng đầy đủ."

    return {
        "value": round(salinity_ppt, 1),
        "status": status,
        "risk_score": risk_score,
        "message": message,
        "action": action,
    }


def evaluate_nitrite_toxicity(
    no2_n_mg_l: float,
    salinity_ppt: float = 15.0,
) -> Dict[str, Any]:
    """
    Đánh giá độc tính Nitrite (NO2-N) động học theo độ mặn thực tế.
    
    Căn cứ khoa học:
    - Lin & Chen (2003): Ngưỡng an toàn NO2-N đối với tôm thẻ chân trắng phụ thuộc độ mặn:
      + Độ mặn 15 ppt: Ngưỡng độc cấp tính là 6.1 mg/L
      + Độ mặn 25 ppt: Ngưỡng độc cấp tính là 15.2 mg/L
      + Độ mặn 35 ppt: Ngưỡng độc cấp tính là 25.7 mg/L
    - Samocha (2019): Độ mặn > 15 ppt cho phép NO2-N < 10 mg/L; Độ mặn < 15 ppt tối đa chỉ 5 mg/L.
    - Valencia-Castañeda et al. (2019): Điều kiện hỗn hợp 3 dạng đạm, ngưỡng an toàn NO2-N <= 0.08 mg/L.
    """
    if salinity_ppt < 15.0:
        safe_limit = 5.0
        danger_limit = 6.1
    elif salinity_ppt <= 25.0:
        safe_limit = 10.0
        danger_limit = 15.2
    else:
        safe_limit = 15.0
        danger_limit = 25.7

    risk_score = 0.0
    action = None

    if no2_n_mg_l <= 0.08:
        status = "OPTIMAL"
        risk_score = 0.0
        message = f"Nitrite ({no2_n_mg_l:.2f} mg/L) đạt chuẩn an toàn tuyệt đối (Valencia-Castañeda et al. 2019)."
    elif no2_n_mg_l <= safe_limit * 0.5:
        status = "OPTIMAL"
        risk_score = 10.0
        message = f"Nitrite ({no2_n_mg_l:.2f} mg/L) ở mức thấp an toàn tại độ mặn {salinity_ppt:.1f} ppt."
    elif no2_n_mg_l <= safe_limit:
        status = "ACCEPTABLE"
        risk_score = 30.0
        message = f"Nitrite ({no2_n_mg_l:.2f} mg/L) trong giới hạn cho phép (ngưỡng an toàn Samocha 2019: {safe_limit} mg/L)."
    elif no2_n_mg_l <= danger_limit:
        status = "WARNING"
        risk_score = 65.0
        message = f"CẢNH BÁO: Nitrite ({no2_n_mg_l:.2f} mg/L) vượt ngưỡng an toàn {safe_limit} mg/L ở độ mặn {salinity_ppt:.1f} ppt (nguy cơ tổn thương mang theo Lin & Chen 2003)!"
        action = "Tăng độ mặn hoặc bổ sung muối NaCl để ion Cl- cạnh tranh ức chế độc tính Nitrite; sục khí mạnh."
    else:
        status = "DANGER"
        risk_score = 90.0
        message = f"NGUY HIỂM: Nitrite ({no2_n_mg_l:.2f} mg/L) vượt ngưỡng độc cấp tính {danger_limit} mg/L (Lin & Chen 2003), nguy cơ tôm ngạt máu và chết hàng loạt!"
        action = "Thay nước tầng đáy, xi-phông loại bỏ bùn bã hữu cơ, bổ sung vi sinh chuyển hóa Nitrite (Nitrospira/Nitrobacter)."

    return {
        "value": round(no2_n_mg_l, 3),
        "salinity_ppt": round(salinity_ppt, 1),
        "safe_limit": safe_limit,
        "danger_limit": danger_limit,
        "status": status,
        "risk_score": risk_score,
        "message": message,
        "action": action,
    }


def evaluate_orp(orp_mv: float) -> Dict[str, Any]:
    """
    Đánh giá Thế Oxy Hóa Khử (ORP - Oxidation Reduction Potential).
    
    Căn cứ khoa học:
    - Nguyễn Hữu Nghĩa et al. (2022): 
      + ORP trong khoảng 150 - 250 mV thúc đẩy quá trình nitrate hóa, kiểm soát vi khuẩn kỵ khí.
      + ORP > 350 mV bắt đầu tiêu diệt vi khuẩn.
      + ORP giảm mạnh < 150 mV ở tuần nuôi thứ 5-6 do chất thải hữu cơ tích tụ dưới đáy ao.
    """
    risk_score = 0.0
    action = None

    if orp_mv < 100.0:
        status = "DANGER"
        risk_score = 85.0
        message = f"NGUY HIỂM: Đáy ao suy thoái yếm khí nặng (ORP = {orp_mv:.0f} mV < 100 mV), khí độc H2S bùng phát từ bùn đáy ao!"
        action = "Xi-phông đáy ao khẩn cấp, tăng cường sục khí đáy và tạt Yucca/men vi sinh xử lý đáy."
    elif orp_mv < 150.0:
        status = "WARNING"
        risk_score = 50.0
        message = f"CẢNH BÁO: ORP = {orp_mv:.0f} mV thấp (< 150 mV), quá trình nitrate hóa bị cản trở (Nguyễn Hữu Nghĩa et al. 2022)."
        action = "Chạy quạt nước tạo dòng gom tụ bùn đáy, kiểm tra tần suất xi-phông."
    elif orp_mv <= 250.0:
        status = "OPTIMAL"
        risk_score = 0.0
        message = f"ORP = {orp_mv:.0f} mV tối ưu (150 - 250 mV), thúc đẩy nitrate hóa và kiểm soát mầm bệnh (Nguyễn Hữu Nghĩa et al. 2022)."
    elif orp_mv <= 350.0:
        status = "ACCEPTABLE"
        risk_score = 15.0
        message = f"ORP = {orp_mv:.0f} mV ở mức oxy hóa cao, môi trường nước trong sạch."
    else:
        status = "WARNING"
        risk_score = 55.0
        message = f"CẢNH BÁO: ORP = {orp_mv:.0f} mV quá cao (> 350 mV), nguy cơ ảnh hưởng mô mang nếu do dư thừa ozone/hóa chất sát trùng."
        action = "Giảm liều lượng chạy máy ozone hoặc chất oxy hóa mạnh."

    return {
        "value": round(orp_mv, 1),
        "status": status,
        "risk_score": risk_score,
        "message": message,
        "action": action,
    }


def evaluate_turbidity(turbidity_ntu: float) -> Dict[str, Any]:
    """
    Đánh giá độ đục và nguy cơ tảo tàn hoặc nước quá trong.
    
    Căn cứ khoa học:
    - Ngô Thụy Diễm Trang et al. (2022): Độ đục phản ánh sự tích tụ của chất lơ lửng, tảo và bùn.
    - Mỹ (2009): Màu nước nuôi tôm tốt nhất là màu trà hoặc xanh nhạt, độ đục kiểm soát 15 - 40 NTU.
    """
    risk_score = 0.0
    action = None

    if turbidity_ntu < 10.0:
        status = "WARNING"
        risk_score = 45.0
        message = f"CẢNH BÁO: Nước quá trong (Độ đục {turbidity_ntu:.1f} NTU < 10 NTU), thiếu phiêu sinh vật, nguy cơ bùng phát rong nhớt đáy ao!"
        action = "Gây lại màu nước ao bằng cám ủ lên men hoặc mật rỉ đường + vi sinh."
    elif turbidity_ntu <= 40.0:
        status = "OPTIMAL"
        risk_score = 0.0
        message = f"Độ đục ({turbidity_ntu:.1f} NTU) tối ưu, phản ánh mật độ tảo thích hợp."
    elif turbidity_ntu <= 60.0:
        status = "ACCEPTABLE"
        risk_score = 20.0
        message = f"Độ đục ({turbidity_ntu:.1f} NTU) ở mức trung bình, cần theo dõi xu hướng tảo."
    elif turbidity_ntu <= 80.0:
        status = "WARNING"
        risk_score = 55.0
        message = f"CẢNH BÁO: Độ đục cao ({turbidity_ntu:.1f} NTU), mật độ tảo đậm hoặc có nhiều phù sa lơ lửng."
        action = "Tăng cường chạy quạt gom bã hữu cơ, hạn chế bón phân/dinh dưỡng."
    else:
        status = "DANGER"
        risk_score = 80.0
        message = f"NGUY HIỂM: Độ đục rất cao ({turbidity_ntu:.1f} NTU > 80 NTU), nguy cơ tảo tàn hàng loạt làm nghẽn mang tôm và tiêu hao oxy đáy ao!"
        action = "Xi-phông xả bớt bùn đáy, đánh khoáng chất kết tủa và bổ sung vi sinh phân hủy xác tảo."

    return {
        "value": round(turbidity_ntu, 1),
        "status": status,
        "risk_score": risk_score,
        "message": message,
        "action": action,
    }


def calculate_shrimp_wqi(
    do_mg_l: float,
    ph: float,
    temp_c: float,
    salinity_ppt: float,
    turbidity_ntu: float,
    tan_mg_l: Optional[float] = None,
    no2_mg_l: Optional[float] = None,
    orp_mv: Optional[float] = None,
    delta_temp_rain: Optional[float] = None,
    delta_ph: Optional[float] = None,
    do_sat_mg_l: Optional[float] = None,
) -> Tuple[float, str, Dict[str, Any], List[str], List[str]]:
    """
    Tính Chỉ Số Chất Lượng Nước Nuôi Tôm Toàn Diện (Shrimp WQI) theo phương pháp bình quân gia quyền.
    Tổng hợp 10 chỉ tiêu thực nghiệm, trả về:
    (wqi_score, classification, parameters_eval, factors_list, action_recommendations)
    
    Phân hạng WQI:
    - 85 - 100: EXCELLENT (Nước hoàn hảo cho tôm tăng trưởng)
    - 70 - 84: GOOD (Nước tốt, điều kiện nuôi thuận lợi)
    - 50 - 69: ACCEPTABLE (Trung bình, cần theo dõi sát)
    - 30 - 49: WARNING (Kém, tôm bị stress sinh lý, giảm ăn)
    - 0 - 29: DANGER (Nguy cấp, đe dọa trực tiếp mạng sống đàn tôm)
    """
    # 1. Đánh giá từng thông số
    eval_do = evaluate_dissolved_oxygen(do_mg_l, do_sat_mg_l)
    eval_ph = evaluate_ph(ph, delta_ph)
    eval_temp = evaluate_temperature(temp_c, delta_temp_rain)
    eval_sal = evaluate_salinity(salinity_ppt)
    eval_turb = evaluate_turbidity(turbidity_ntu)

    params_eval: Dict[str, Any] = {
        "dissolved_oxygen": eval_do,
        "ph": eval_ph,
        "temperature": eval_temp,
        "salinity": eval_sal,
        "turbidity": eval_turb,
    }

    # Tính điểm thành phần chất lượng q_i (0 đến 100, 100 là tốt nhất)
    # q_i = 100 - risk_score
    q_weights: List[Tuple[float, float]] = [
        (100.0 - eval_do["risk_score"], 0.25),   # DO: Trọng số 0.25 (sinh mạng)
        (100.0 - eval_ph["risk_score"], 0.15),   # pH: Trọng số 0.15
        (100.0 - eval_temp["risk_score"], 0.10), # Temp: Trọng số 0.10
        (100.0 - eval_sal["risk_score"], 0.08),  # Salinity: Trọng số 0.08
        (100.0 - eval_turb["risk_score"], 0.07), # Turbidity: Trọng số 0.07
    ]

    total_weight = 0.25 + 0.15 + 0.10 + 0.08 + 0.07

    # 2. Xử lý khí độc TAN / NH3 nếu có
    if tan_mg_l is not None:
        toxic_nh3 = calculate_toxic_ammonia_nh3(tan_mg_l, temp_c, ph, salinity_ppt)
        if toxic_nh3 > 0.05:
            nh3_status = "DANGER"
            nh3_risk = 90.0
            nh3_msg = f"NGUY HIỂM: Khí độc NH3 = {toxic_nh3:.3f} mg/L (>0.05 mg/L), gây phá hủy mô mang tôm (Fregoso et al. 2017)!"
            nh3_act = "Thay nước, đánh Yucca hoặc vi sinh xử lý khí độc khẩn cấp; cắt cữ ăn."
        elif toxic_nh3 > 0.02:
            nh3_status = "WARNING"
            nh3_risk = 55.0
            nh3_msg = f"CẢNH BÁO: Khí độc NH3 = {toxic_nh3:.3f} mg/L vượt mức an toàn sinh học (0.02 mg/L)."
            nh3_act = "Tăng cường chạy quạt nước giải phóng khí độc, kiểm tra thức ăn dư thừa."
        else:
            nh3_status = "OPTIMAL"
            nh3_risk = 0.0
            nh3_msg = f"Khí độc NH3 = {toxic_nh3:.3f} mg/L ở mức an toàn (<0.02 mg/L) theo Albert (1973)."
            nh3_act = None

        eval_nh3 = {
            "value": toxic_nh3,
            "tan_raw": round(tan_mg_l, 2),
            "status": nh3_status,
            "risk_score": nh3_risk,
            "message": nh3_msg,
            "action": nh3_act,
        }
        params_eval["toxic_ammonia"] = eval_nh3
        q_weights.append((100.0 - nh3_risk, 0.20))
        total_weight += 0.20

    # 3. Xử lý Nitrite NO2 nếu có
    if no2_mg_l is not None:
        eval_no2 = evaluate_nitrite_toxicity(no2_mg_l, salinity_ppt)
        params_eval["nitrite"] = eval_no2
        q_weights.append((100.0 - eval_no2["risk_score"], 0.15))
        total_weight += 0.15

    # 4. Xử lý ORP nếu có
    if orp_mv is not None:
        eval_orp_data = evaluate_orp(orp_mv)
        params_eval["orp"] = eval_orp_data
        q_weights.append((100.0 - eval_orp_data["risk_score"], 0.07))
        total_weight += 0.07

    # Tính điểm WQI chuẩn hóa
    weighted_sum = sum(q * w for q, w in q_weights)
    wqi_score = round(max(0.0, min(100.0, weighted_sum / total_weight)), 1)

    # Phân loại WQI
    if wqi_score >= 85.0:
        classification = "EXCELLENT"
    elif wqi_score >= 70.0:
        classification = "GOOD"
    elif wqi_score >= 50.0:
        classification = "ACCEPTABLE"
    elif wqi_score >= 30.0:
        classification = "WARNING"
    else:
        classification = "DANGER"

    # Tổng hợp factors và action recommendations
    factors: List[str] = []
    actions: List[str] = []

    for param_name, param_data in params_eval.items():
        if param_data["status"] in ["WARNING", "DANGER"]:
            factors.append(param_data["message"])
        if param_data.get("action"):
            actions.append(param_data["action"])

    if not factors:
        factors.append("Mọi chỉ số môi trường nước đạt chuẩn tối ưu theo QCVN 02-19:2014.")

    return wqi_score, classification, params_eval, factors, actions
