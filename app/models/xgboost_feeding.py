"""
Mô hình XGBoost Feeding Forecast
Do ML-Modeling-Agent chủ trì.
Tuân thủ tuyệt đối bộ tham số thực nghiệm:
- n_estimators=600, learning_rate=0.05, max_depth=6, subsample=0.8, colsample_bytree=0.8, random_state=42
- 7 biến thực nghiệm bắt buộc (Feature Integrity Rule)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from app.services.pipeline import (
    REQUIRED_FEEDING_FEATURES,
    TimeSeriesDataPipeline,
)

logger = logging.getLogger("ai_service.models.xgboost")

# Bộ siêu tham số thực nghiệm bắt buộc
DEFAULT_XGBOOST_PARAMS = {
    "n_estimators": 600,
    "learning_rate": 0.05,
    "max_depth": 6,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "objective": "reg:squarederror",
    "n_jobs": -1,
}


class XGBoostFeedingTrainer:
    """
    Quản lý khởi tạo, cấu hình và huấn luyện mô hình XGBoost dự báo lượng thức ăn cho tôm.
    """

    def __init__(
        self,
        params: Optional[Dict] = None,
        feature_cols: Tuple[str, ...] = REQUIRED_FEEDING_FEATURES,
        target_col: str = "feed_amount_kg",
        model_path: str = "trained_models/xgboost_feeding_model.joblib",
        scaler_path: str = "trained_models/feeding_scaler.joblib",
        metadata_path: str = "trained_models/model_metadata.json",
    ):
        self.params = params or DEFAULT_XGBOOST_PARAMS.copy()
        self.feature_cols = list(feature_cols)
        self.target_col = target_col
        self.model_path = Path(model_path)
        self.scaler_path = Path(scaler_path)
        self.metadata_path = Path(metadata_path)

        self.model: Optional[XGBRegressor] = None
        self.pipeline = TimeSeriesDataPipeline(
            feature_cols=self.feature_cols,
            target_col=self.target_col,
            scaler_path=str(self.scaler_path),
        )

    def build_model(self) -> XGBRegressor:
        """Khởi tạo thực thể XGBRegressor với bộ tham số thực nghiệm"""
        self.model = XGBRegressor(**self.params)
        return self.model

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
    ) -> XGBRegressor:
        """
        Huấn luyện mô hình XGBoost trên dữ liệu đã được chuẩn hóa.
        
        Args:
            X_train: Ma trận đặc trưng tập train (n_samples, 7) đã qua scaler.transform.
            y_train: Vector lượng thức ăn thực tế tập train.
            X_val: Ma trận validation tùy chọn.
            y_val: Vector mục tiêu validation.
            
        Returns:
            XGBRegressor đã được fit.
        """
        if self.model is None:
            self.build_model()

        logger.info(
            f"[XGBoostFeedingTrainer] Bắt đầu huấn luyện với {X_train.shape[0]} mẫu, "
            f"7 đặc trưng: {self.feature_cols}, tham số: {self.params}"
        )

        eval_set = [(X_train, y_train)]
        if X_val is not None and y_val is not None:
            eval_set.append((X_val, y_val))

        self.model.fit(
            X_train,
            y_train,
            eval_set=eval_set,
            verbose=False,
        )

        logger.info("[XGBoostFeedingTrainer] Huấn luyện hoàn thành thành công.")
        return self.model

    def predict(
        self,
        X: Union[np.ndarray, pd.DataFrame, List[float]],
        is_scaled: bool = True,
    ) -> np.ndarray:
        """
        Dự báo lượng thức ăn (kg) từ vector đặc trưng.
        
        Args:
            X: Ma trận hoặc vector chứa 7 đặc trưng thực nghiệm.
            is_scaled: Nếu False, sử dụng scaler đã lưu để scale dữ liệu trước khi đưa vào mô hình.
            
        Returns:
            np.ndarray: Lượng thức ăn dự báo (kg).
        """
        if self.model is None:
            raise ValueError("Mô hình chưa được huấn luyện hoặc tải từ file checkpoint.")

        # Xử lý format đầu vào thành 2D array
        if isinstance(X, pd.DataFrame):
            X_arr = X[self.feature_cols].to_numpy(dtype=np.float64)
        elif isinstance(X, list):
            X_arr = np.array(X, dtype=np.float64)
            if X_arr.ndim == 1:
                X_arr = X_arr.reshape(1, -1)
        elif isinstance(X, np.ndarray):
            X_arr = X if X.ndim == 2 else X.reshape(1, -1)
        else:
            raise TypeError(f"Kiểu dữ liệu đầu vào không hỗ trợ: {type(X)}")

        if X_arr.shape[1] != len(self.feature_cols):
            raise ValueError(
                f"Số lượng đặc trưng không khớp: nhận {X_arr.shape[1]}, yêu cầu đúng {len(self.feature_cols)} biến."
            )

        if not is_scaled:
            scaler = self.pipeline.load_scaler()
            X_arr = scaler.transform(X_arr)

        raw_preds = self.model.predict(X_arr)
        # Lượng thức ăn sinh học tối thiểu là 0.5 kg (không bao giờ âm)
        return np.clip(raw_preds, a_min=0.5, a_max=None)

    def get_feature_importances(self) -> Dict[str, float]:
        """Trả về mức độ quan trọng (Feature Importances) tương ứng với 7 biến thực nghiệm"""
        if self.model is None:
            raise ValueError("Mô hình chưa được fit.")
        importances = self.model.feature_importances_
        return {feat: float(imp) for feat, imp in zip(self.feature_cols, importances)}

    def get_hyperparameters(self) -> Dict:
        """Trả về bản sao từ điển siêu tham số"""
        return self.params.copy()

    def evaluate(
        self,
        X_test: np.ndarray,
        y_test: np.ndarray,
        is_scaled: bool = True,
        assert_acceptance: bool = False,
    ) -> Dict[str, float]:
        """
        Đánh giá độ chính xác của mô hình trên tập kiểm thử độc lập.
        
        Args:
            X_test: Ma trận kiểm thử chứa 7 biến thực nghiệm.
            y_test: Vector lượng thức ăn thực tế.
            is_scaled: True nếu X_test đã qua scaler.transform.
            assert_acceptance: Nếu True, tự động kiểm tra điều kiện chuẩn khoa học (R2 >= 0.78, MAPE <= 8.7%).
            
        Returns:
            Dict chứa các chỉ số: r2, mape, mae, rmse.
        """
        y_pred = self.predict(X_test, is_scaled=is_scaled)
        metrics = evaluate_model(y_test, y_pred)

        logger.info(
            f"[TASK-ML-02 Đánh Giá Mô Hình] R2={metrics['r2']:.4f}, MAPE={metrics['mape']:.2f}%, "
            f"MAE={metrics['mae']:.2f} kg, RMSE={metrics['rmse']:.2f} kg"
        )

        if assert_acceptance:
            validate_scientific_acceptance(metrics)

        return metrics

    def save_model(
        self,
        model_path: Optional[Union[str, Path]] = None,
        metadata_path: Optional[Union[str, Path]] = None,
        metrics: Optional[Dict[str, float]] = None,
    ) -> Tuple[Path, Path]:
        """
        Đóng gói và xuất file trọng số mô hình (.joblib) và metadata (.json).
        
        Args:
            model_path: Đường dẫn file lưu trọng số (.joblib). Mặc định dùng self.model_path.
            metadata_path: Đường dẫn file lưu metadata (.json). Mặc định dùng self.metadata_path.
            metrics: Từ điển các chỉ số đánh giá (R2, MAPE, MAE, RMSE).
            
        Returns:
            Tuple[Path, Path]: Đường dẫn file model và file metadata đã ghi.
        """
        if self.model is None:
            raise ValueError("Không thể lưu mô hình chưa được huấn luyện hoặc khởi tạo.")

        m_path = Path(model_path) if model_path else self.model_path
        meta_path = Path(metadata_path) if metadata_path else self.metadata_path

        m_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Lưu trọng số mô hình .joblib
        joblib.dump(self.model, m_path)
        logger.info(f"[TASK-ML-04] Đã lưu trọng số mô hình XGBoost vào: {m_path}")

        # 2. Xây dựng và lưu model_metadata.json
        metadata = {
            "model_name": "xgboost_feeding_model",
            "version": "1.0.0",
            "model_type": "XGBRegressor",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "feature_integrity": {
                "count": len(self.feature_cols),
                "features": self.feature_cols,
                "target": self.target_col,
            },
            "hyperparameters": self.get_hyperparameters(),
            "metrics": metrics or {},
            "feature_importances": self.get_feature_importances(),
            "scaler_path": str(self.scaler_path),
            "scientific_acceptance": {
                "min_r2_threshold": 0.78,
                "max_mape_threshold": 8.7,
                "passed": bool(
                    metrics
                    and metrics.get("r2", 0) >= 0.78
                    and metrics.get("mape", 100) <= 8.7
                ) if metrics else False,
            },
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        logger.info(f"[TASK-ML-04] Đã xuất file metadata vào: {meta_path}")

        return m_path, meta_path

    def load_model(self, model_path: Optional[Union[str, Path]] = None) -> XGBRegressor:
        """
        Nạp trọng số mô hình từ file .joblib đã lưu vào bộ nhớ.
        
        Args:
            model_path: Đường dẫn file trọng số. Mặc định dùng self.model_path.
            
        Returns:
            XGBRegressor: Thực thể mô hình sẵn sàng suy luận.
        """
        m_path = Path(model_path) if model_path else self.model_path
        if not m_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file trọng số mô hình tại: {m_path}")

        self.model = joblib.load(m_path)
        logger.info(f"[TASK-ML-04] Nạp mô hình XGBoost thành công từ: {m_path}")
        return self.model


# ==============================================================================
# TASK-ML-02: Đánh Giá Độ Chính Xác & Cam Kết Chuẩn Khoa Học
# ==============================================================================

from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def evaluate_model(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """
    Tính toán 4 chỉ số đo lường hiệu năng của mô hình hồi quy:
    1. R2 (Hệ số xác định)
    2. MAPE (Mean Absolute Percentage Error - %)
    3. MAE (Mean Absolute Error - kg)
    4. RMSE (Root Mean Squared Error - kg)
    """
    y_true_arr = np.asarray(y_true, dtype=np.float64).flatten()
    y_pred_arr = np.asarray(y_pred, dtype=np.float64).flatten()

    r2 = float(r2_score(y_true_arr, y_pred_arr))
    
    # Tính MAPE an toàn (tránh chia cho 0)
    denom = np.maximum(np.abs(y_true_arr), 1e-6)
    mape = float(np.mean(np.abs((y_true_arr - y_pred_arr) / denom)) * 100.0)
    
    mae = float(mean_absolute_error(y_true_arr, y_pred_arr))
    rmse = float(np.sqrt(mean_squared_error(y_true_arr, y_pred_arr)))

    return {
        "r2": round(r2, 4),
        "mape": round(mape, 2),
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
    }


def validate_scientific_acceptance(
    metrics: Dict[str, float],
    min_r2: float = 0.78,
    max_mape: float = 8.7,
) -> bool:
    """
    Kiểm tra tiêu chuẩn khoa học khắt khe của dự án:
    - R² >= 0.78
    - MAPE <= 8.7%
    
    Ném lỗi ValueError nếu mô hình không thỏa mãn để ngăn chặn xuất mô hình kém chất lượng.
    """
    r2_val = metrics.get("r2", 0.0)
    mape_val = metrics.get("mape", 100.0)

    is_r2_ok = r2_val >= min_r2
    is_mape_ok = mape_val <= max_mape

    if not is_r2_ok or not is_mape_ok:
        err_msg = (
            f"[Scientific Validation Failed] Mô hình không đạt chuẩn khoa học bắt buộc! "
            f"Kết quả hiện tại: R²={r2_val:.4f} (yêu cầu >= {min_r2}), MAPE={mape_val:.2f}% (yêu cầu <= {max_mape}%)."
        )
        logger.error(err_msg)
        raise ValueError(err_msg)

    logger.info(
        f"[Scientific Validation Passed] Mô hình đạt chuẩn khoa học: R²={r2_val:.4f} >= {min_r2}, MAPE={mape_val:.2f}% <= {max_mape}%."
    )
    return True


def train_and_validate_feeding_model(
    df: Optional[pd.DataFrame] = None,
    test_ratio: float = 0.20,
    assert_acceptance: bool = True,
    save_artifacts: bool = True,
    model_path: str = "trained_models/xgboost_feeding_model.joblib",
    scaler_path: str = "trained_models/feeding_scaler.joblib",
    metadata_path: str = "trained_models/model_metadata.json",
) -> Tuple[XGBoostFeedingTrainer, Dict[str, float]]:
    """
    Quy trình tích hợp hoàn chỉnh:
    1. Chuẩn bị dữ liệu và phân chia Time-Blocked Split (chống rò rỉ dữ liệu).
    2. Huấn luyện mô hình XGBoost với 600 estimators, lr=0.05, max_depth=6.
    3. Đánh giá kiểm định trên tập kiểm thử độc lập (R2 >= 0.78, MAPE <= 8.7%).
    4. Xuất trọng số .joblib và model_metadata.json nếu save_artifacts=True.
    """
    from app.data.generate_synthetic_data import generate_synthetic_feeding_dataset

    if df is None:
        logger.info("Chưa có DataFrame đầu vào, tự động sinh bộ dữ liệu thực nghiệm mẫu 10 ao x 90 ngày...")
        df = generate_synthetic_feeding_dataset(num_ponds=10, cycle_days=90, random_seed=42)

    pipeline = TimeSeriesDataPipeline(scaler_path=scaler_path)
    X_train_s, y_train, X_test_s, y_test, scaler = pipeline.prepare_time_blocked_split(
        df, test_ratio=test_ratio, save_scaler=True
    )

    trainer = XGBoostFeedingTrainer(
        model_path=model_path,
        scaler_path=scaler_path,
        metadata_path=metadata_path,
    )
    trainer.train(X_train_s, y_train, X_val=X_test_s, y_val=y_test)

    metrics = trainer.evaluate(X_test_s, y_test, is_scaled=True, assert_acceptance=assert_acceptance)

    if save_artifacts:
        trainer.save_model(metrics=metrics)

    return trainer, metrics


def load_trained_feeding_model(
    model_path: str = "trained_models/xgboost_feeding_model.joblib",
    scaler_path: str = "trained_models/feeding_scaler.joblib",
    metadata_path: str = "trained_models/model_metadata.json",
) -> XGBoostFeedingTrainer:
    """
    Tiện ích nạp sẵn mô hình và scaler vào RAM phục vụ API inference (FastAPI lifespan).
    Đảm bảo thời gian phản hồi < 500ms theo Inference Latency Rule.
    """
    trainer = XGBoostFeedingTrainer(
        model_path=model_path,
        scaler_path=scaler_path,
        metadata_path=metadata_path,
    )
    trainer.load_model()
    # Tải trước scaler để sẵn sàng dự báo
    trainer.pipeline.load_scaler()
    logger.info("[load_trained_feeding_model] Sẵn sàng phục vụ suy luận.")
    return trainer

