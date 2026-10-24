"""
Unit Tests: Động Cơ Đánh Giá & Phân Tích Chất Lượng Nước Đa Thông Số (Multi-Parameter Water Quality Engine)
Căn cứ khoa học 100% dựa trên các công trình nghiên cứu đã công bố:
- Đỗ Doãn Dung et al. (2025)
- Nguyễn Hữu Nghĩa et al. (2022)
- Ngô Thụy Diễm Trang et al. (2022)
- QCVN 02-19:2014/BNNPTNT
- Lin & Chen (2003); Samocha (2019)
- Albert (1973); Emerson et al. (1975)
- Boyd & Fast (1992); Weitkamp et al. (1980)
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.water_quality import (
    calculate_shrimp_wqi,
    calculate_toxic_ammonia_nh3,
    evaluate_dissolved_oxygen,
    evaluate_nitrite_toxicity,
    evaluate_orp,
    evaluate_ph,
    evaluate_salinity,
    evaluate_temperature,
    evaluate_turbidity,
)


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_toxic_ammonia_nh3_equilibrium_albert_emerson():
    """
    Kiểm tra phương trình nhiệt động học Albert (1973) & Emerson et al. (1975).
    Độc tính NH3 tăng vọt khi pH và nhiệt độ tăng.
    """
    # 1. Điều kiện bình thường: T = 28°C, pH = 7.6, S = 15 ppt, TAN = 0.5 mg/L
    nh3_normal = calculate_toxic_ammonia_nh3(tan_mg_l=0.5, temperature_c=28.0, ph=7.6, salinity_ppt=15.0)
    assert nh3_normal < 0.02, f"NH3 phải an toàn (<0.02 mg/L), thực tế: {nh3_normal}"

    # 2. Điều kiện kiềm cao, nhiệt cao: T = 32°C, pH = 8.8, S = 15 ppt, TAN = 1.0 mg/L
    nh3_toxic = calculate_toxic_ammonia_nh3(tan_mg_l=1.0, temperature_c=32.0, ph=8.8, salinity_ppt=15.0)
    assert nh3_toxic > 0.05, f"NH3 phải vượt ngưỡng độc hại (>0.05 mg/L), thực tế: {nh3_toxic}"
    assert nh3_toxic > nh3_normal * 5.0, "Độc tính NH3 phải tăng vọt nhiều lần khi pH và T tăng"

    # 3. Khi TAN = 0
    assert calculate_toxic_ammonia_nh3(tan_mg_l=0.0, temperature_c=30.0, ph=8.0) == 0.0


def test_nitrite_toxicity_salinity_dependent_lin_chen():
    """
    Kiểm tra giải thuật phân tầng độc tính Nitrite (NO2-N) động theo độ mặn
    Căn cứ: Lin & Chen (2003) và Samocha (2019).
    """
    # Ở độ mặn thấp 10 ppt (< 15 ppt): Ngưỡng an toàn là 5.0 mg/L, nguy cấp là 6.1 mg/L
    eval_low_sal = evaluate_nitrite_toxicity(no2_n_mg_l=5.5, salinity_ppt=10.0)
    assert eval_low_sal["status"] == "WARNING"
    assert "tổn thương mang" in eval_low_sal["message"].lower() or "vượt ngưỡng an toàn" in eval_low_sal["message"].lower()

    # Ở độ mặn 25 ppt: Cùng mức NO2 5.5 mg/L lại hoàn toàn ACCEPTABLE vì ion Cl- ức chế độc tính
    eval_high_sal = evaluate_nitrite_toxicity(no2_n_mg_l=5.5, salinity_ppt=25.0)
    assert eval_high_sal["status"] == "ACCEPTABLE"
    assert eval_high_sal["risk_score"] < eval_low_sal["risk_score"]

    # Mức NO2 cực thấp (Valencia-Castañeda 2019: <= 0.08 mg/L)
    eval_optimal = evaluate_nitrite_toxicity(no2_n_mg_l=0.05, salinity_ppt=15.0)
    assert eval_optimal["status"] == "OPTIMAL"
    assert eval_optimal["risk_score"] == 0.0


def test_dissolved_oxygen_and_gas_bubble_supersaturation():
    """
    Kiểm tra Oxy hòa tan, bao gồm cảnh báo thiếu oxy và siêu bão hòa (Boyd & Fast 1992, Weitkamp 1980).
    """
    # 1. Oxy tối ưu
    eval_opt = evaluate_dissolved_oxygen(do_mg_l=6.2)
    assert eval_opt["status"] == "OPTIMAL"
    assert eval_opt["risk_score"] == 0.0

    # 2. Ngạt khí nguy cấp DO < 3.0
    eval_hypoxia = evaluate_dissolved_oxygen(do_mg_l=2.4)
    assert eval_hypoxia["status"] == "DANGER"
    assert eval_hypoxia["risk_score"] >= 80.0
    assert "nguy cấp" in eval_hypoxia["message"].lower()

    # 3. Siêu bão hòa khí DO > 20 mg/L (Boyd & Fast 1992)
    eval_super = evaluate_dissolved_oxygen(do_mg_l=21.5, do_saturation_mg_l=7.5)
    assert eval_super["status"] == "DANGER"
    assert "chấn thương bóng khí" in eval_super["message"].lower() or "bóng khí" in eval_super["message"].lower()
    assert eval_super["action"] is not None


def test_ph_and_day_night_fluctuation():
    """
    Kiểm tra đánh giá pH và biên độ dao động Delta pH ngày/đêm (Ngô Thụy Diễm Trang et al. 2022).
    """
    # 1. pH tối ưu, biên độ nhỏ
    eval_opt = evaluate_ph(ph=7.8, delta_ph_day_night=0.3)
    assert eval_opt["status"] == "OPTIMAL"
    assert eval_opt["risk_score"] == 0.0

    # 2. pH tối ưu nhưng biên độ ngày đêm quá lớn (>1.0) báo hiệu tảo nở hoa
    eval_bloom = evaluate_ph(ph=8.2, delta_ph_day_night=1.2)
    assert eval_bloom["status"] == "DANGER"
    assert "dao động ngày/đêm quá lớn" in eval_bloom["message"].lower() or "tảo nở hoa" in eval_bloom["message"].lower()

    # 3. pH axit hóa nghiêm trọng < 6.5
    eval_acid = evaluate_ph(ph=6.2)
    assert eval_acid["status"] == "DANGER"
    assert "axit hóa" in eval_acid["message"].lower()


def test_temperature_and_rain_shock_alert():
    """
    Kiểm tra cảnh báo sốc nhiệt sau mưa sụt giảm 3-5°C (Đỗ Doãn Dung et al. 2025).
    """
    # 1. Nhiệt độ bình thường
    eval_normal = evaluate_temperature(temp_c=29.5)
    assert eval_normal["status"] == "OPTIMAL"

    # 2. Sốc nhiệt do mưa lớn sụt 3.5°C
    eval_rain_shock = evaluate_temperature(temp_c=26.0, delta_temp_rain=-3.5)
    assert eval_rain_shock["status"] == "DANGER"
    assert "sốc nước mưa" in eval_rain_shock["message"].lower() or "đỗ doãn dung" in eval_rain_shock["message"].lower()
    assert "cắt giảm ngay 30 - 50%" in eval_rain_shock["action"].lower() or "giảm" in eval_rain_shock["action"].lower()


def test_orp_bottom_deterioration():
    """
    Kiểm tra đánh giá Thế Oxy Hóa Khử ORP (Nguyễn Hữu Nghĩa et al. 2022).
    """
    # 1. ORP tối ưu thúc đẩy nitrate hóa (150 - 250 mV)
    eval_opt = evaluate_orp(orp_mv=215.0)
    assert eval_opt["status"] == "OPTIMAL"
    assert eval_opt["risk_score"] == 0.0

    # 2. ORP thấp < 100 mV suy thoái yếm khí đáy ao
    eval_bad = evaluate_orp(orp_mv=85.0)
    assert eval_bad["status"] == "DANGER"
    assert "yếm khí" in eval_bad["message"].lower() or "h2s" in eval_bad["message"].lower()
    assert eval_bad["action"] is not None


def test_turbidity_and_algae_crash():
    """
    Kiểm tra độ đục: tối ưu 15-40 NTU, nước quá trong < 10 NTU, tảo tàn > 80 NTU.
    """
    # 1. Tối ưu
    eval_opt = evaluate_turbidity(turbidity_ntu=30.0)
    assert eval_opt["status"] == "OPTIMAL"

    # 2. Nước quá trong
    eval_clear = evaluate_turbidity(turbidity_ntu=7.0)
    assert eval_clear["status"] == "WARNING"
    assert "rong nhớt" in eval_clear["message"].lower()

    # 3. Tảo tàn nghiêm trọng > 80 NTU
    eval_crash = evaluate_turbidity(turbidity_ntu=95.0)
    assert eval_crash["status"] == "DANGER"
    assert "tảo tàn" in eval_crash["message"].lower() or "nghẽn mang" in eval_crash["message"].lower()


def test_comprehensive_shrimp_wqi_calculation():
    """
    Kiểm tra Chỉ số Chất lượng nước tổng hợp Shrimp WQI (0-100) theo đa kịch bản.
    """
    # Kịch bản 1: Điều kiện hoàn hảo
    wqi_score, wqi_class, params, factors, actions = calculate_shrimp_wqi(
        do_mg_l=6.5,
        ph=7.9,
        temp_c=29.0,
        salinity_ppt=18.0,
        turbidity_ntu=28.0,
        tan_mg_l=0.2,
        no2_mg_l=0.04,
        orp_mv=210.0,
    )
    assert wqi_score >= 85.0, f"WQI phải đạt EXCELLENT, thực tế: {wqi_score}"
    assert wqi_class == "EXCELLENT"
    assert len(actions) == 0

    # Kịch bản 2: Bùng phát khí độc NH3 và sụt DO
    wqi_bad, class_bad, params_bad, factors_bad, actions_bad = calculate_shrimp_wqi(
        do_mg_l=3.2,
        ph=8.9,
        temp_c=32.5,
        salinity_ppt=15.0,
        turbidity_ntu=75.0,
        tan_mg_l=1.8, # NH3 sẽ tăng vọt
        no2_mg_l=8.5,
        orp_mv=95.0,
    )
    assert wqi_bad < 50.0, f"WQI phải ở mức WARNING hoặc DANGER, thực tế: {wqi_bad}"
    assert class_bad in ["WARNING", "DANGER"]
    assert len(factors_bad) >= 3
    assert len(actions_bad) >= 2


def test_api_predict_multi_parameter_enrichment(client):
    """
    Kiểm tra tính tương thích 100% với Core Backend NestJS của endpoint POST /api/predict
    đồng thời xác thực các trường mở rộng đa thông số (WQI, toxicAmmoniaNH3, actionRecommendations).
    """
    payload = {
        "pondId": "POND_MULTI_01",
        "temperature": 29.5,
        "ph": 8.1,
        "salinity": 16.0,
        "dissolvedOxygen": 5.8,
        "turbidity": 25.0,
        "tan": 0.4,
        "no2": 0.5,
        "orp": 210.0,
    }

    response = client.post("/api/predict", json=payload)
    assert response.status_code == 200
    data = response.json()

    # 1. Khớp 100% các trường bắt buộc của NestJS PredictionsService
    assert "predictedDO" in data
    assert "predictedPH" in data
    assert "riskScore" in data
    assert "riskLevel" in data
    assert "alert" in data
    assert "factors" in data
    assert "timestamp" in data
    assert data["riskLevel"] in ["SAFE", "WARNING", "DANGER"]

    # 2. Xác thực các trường làm giàu đa thông số
    assert "wqi" in data
    assert data["wqi"] is not None
    assert "wqiClassification" in data
    assert data["wqiClassification"] in ["EXCELLENT", "GOOD", "ACCEPTABLE", "WARNING", "DANGER"]
    assert "toxicAmmoniaNH3" in data
    assert "parametersRisk" in data
    assert "actionRecommendations" in data


def test_api_comprehensive_assessment_endpoint(client):
    """
    Kiểm tra endpoint chuyên sâu POST /api/v1/ai/water-quality/comprehensive-assessment
    cung cấp trích dẫn khoa học và bảng đánh giá chi tiết 10 chỉ tiêu.
    """
    payload = {
        "pondId": "POND_A02",
        "temperature": 28.5,
        "ph": 7.8,
        "salinity": 15.0,
        "dissolvedOxygen": 5.4,
        "turbidity": 32.0,
        "tan": 0.3,
        "no2": 0.6,
        "orp": 195.0,
        "alkalinity": 135.0,
    }

    response = client.post("/api/v1/ai/water-quality/comprehensive-assessment", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["pond_id"] == "POND_A02"
    assert data["wqi_score"] > 70.0
    assert data["wqi_classification"] in ["EXCELLENT", "GOOD"]
    assert "scientific_citations" in data
    assert len(data["scientific_citations"]) >= 5
    assert any("Minh Phú - Lộc An" in cit or "Đỗ Doãn Dung" in cit for cit in data["scientific_citations"])
    assert any("Nguyễn Hữu Nghĩa" in cit or "RIA1" in cit for cit in data["scientific_citations"])
    assert any("Ngô Thụy Diễm Trang" in cit or "Sóc Trăng" in cit for cit in data["scientific_citations"])
    assert data["latency_ms"] < 500.0
