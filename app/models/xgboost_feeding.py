"""
Mô hình XGBoost Feeding Forecast
Do ML-Modeling-Agent chủ trì.
Tuân thủ tuyệt đối bộ tham số thực nghiệm:
- n_estimators=600, learning_rate=0.05, max_depth=6, subsample=0.8, colsample_bytree=0.8, random_state=42
- 7 biến thực nghiệm bắt buộc (Feature Integrity Rule)
"""

import logging
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
    ):
        self.params = params or DEFAULT_XGBOOST_PARAMS.copy()
        self.feature_cols = list(feature_cols)
        self.target_col = target_col
        self.model_path = Path(model_path)
        self.scaler_path = Path(scaler_path)

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
