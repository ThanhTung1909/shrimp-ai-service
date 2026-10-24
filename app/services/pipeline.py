"""
AquaSense AI Data Pipeline Service
Phụ trách trích xuất, làm sạch và chuẩn bị dữ liệu chuỗi thời gian từ TimescaleDB.
Do Data-Pipeline-Agent chủ trì.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Union, Sequence, Generator, List, Tuple
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database import SessionLocal, get_engine

logger = logging.getLogger("ai_service.pipeline")

SQL_TELEMETRY_TIME_BUCKET = """
SELECT 
    time_bucket(:bucket_interval, td.recorded_at) AS bucket_time,
    d.pond_id,
    AVG(td.temperature) AS avg_temperature,
    AVG(td.ph) AS avg_ph,
    AVG(td.salinity) AS avg_salinity,
    AVG(td.dissolved_oxygen) AS avg_dissolved_oxygen,
    MIN(td.dissolved_oxygen) AS min_dissolved_oxygen,
    MAX(td.dissolved_oxygen) AS max_dissolved_oxygen,
    AVG(td.turbidity) AS avg_turbidity,
    AVG(td.water_level) AS avg_water_level,
    COUNT(td.id) AS sample_count
FROM telemetry_data td
JOIN device d ON td.device_id = d.device_id
WHERE d.pond_id = :pond_id
  AND td.recorded_at >= :start_time
  AND td.recorded_at <= :end_time
GROUP BY bucket_time, d.pond_id
ORDER BY bucket_time ASC;
"""

SQL_LATEST_POND_TELEMETRY = """
SELECT 
    td.recorded_at,
    d.pond_id,
    td.temperature,
    td.ph,
    td.salinity,
    td.dissolved_oxygen,
    td.turbidity,
    td.water_level
FROM telemetry_data td
JOIN device d ON td.device_id = d.device_id
WHERE d.pond_id = :pond_id
ORDER BY td.recorded_at DESC
LIMIT :limit;
"""


def fetch_telemetry_time_bucket(
    pond_id: str,
    start_time: datetime,
    end_time: datetime,
    bucket_interval: str = "15 minutes",
    session: Optional[Session] = None,
) -> pd.DataFrame:
    """
    Truy xuất chuỗi thời gian telemetry được gom cụm theo time_bucket của TimescaleDB.
    
    Args:
        pond_id: UUID của ao nuôi cần truy xuất dữ liệu.
        start_time: Mốc thời gian bắt đầu.
        end_time: Mốc thời gian kết thúc.
        bucket_interval: Khoảng gom cụm của TimescaleDB (mặc định: '15 minutes').
        session: SQLAlchemy Session tùy chọn. Nếu None, tự tạo session và đóng sau khi truy vấn.
        
    Returns:
        pd.DataFrame chứa chuỗi thời gian đã gom cụm với index là 'bucket_time'.
    """
    logger.info(
        f"[fetch_telemetry_time_bucket] Pond={pond_id}, "
        f"Window=[{start_time.isoformat()} -> {end_time.isoformat()}], Bucket={bucket_interval}"
    )

    close_session_after = False
    if session is None:
        session = SessionLocal()
        close_session_after = True

    try:
        params = {
            "pond_id": pond_id,
            "start_time": start_time,
            "end_time": end_time,
            "bucket_interval": bucket_interval,
        }
        result = session.execute(text(SQL_TELEMETRY_TIME_BUCKET), params)
        rows = result.fetchall()
        columns = list(result.keys())

        if not rows:
            logger.warning(f"Không có dữ liệu telemetry cho ao {pond_id} trong khoảng thời gian chỉ định.")
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame(rows, columns=columns)
        df["bucket_time"] = pd.to_datetime(df["bucket_time"], utc=True)
        df.set_index("bucket_time", inplace=True)
        return df

    except Exception as e:
        logger.error(f"[fetch_telemetry_time_bucket Error] {e}")
        raise e
    finally:
        if close_session_after:
            session.close()


def fetch_latest_pond_telemetry(
    pond_id: str,
    limit: int = 10,
    session: Optional[Session] = None,
) -> pd.DataFrame:
    """
    Truy xuất N bản ghi telemetry mới nhất của một ao nuôi (không qua time_bucket).
    """
    close_session_after = False
    if session is None:
        session = SessionLocal()
        close_session_after = True

    try:
        params = {"pond_id": pond_id, "limit": limit}
        result = session.execute(text(SQL_LATEST_POND_TELEMETRY), params)
        rows = result.fetchall()
        columns = list(result.keys())

        if not rows:
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame(rows, columns=columns)
        df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)
        return df
    finally:
        if close_session_after:
            session.close()


BIOLOGICAL_LIMITS = {
    "temperature": (15.0, 42.0),
    "avg_temperature": (15.0, 42.0),
    "ph": (5.5, 10.0),
    "avg_ph": (5.5, 10.0),
    "salinity": (0.0, 45.0),
    "avg_salinity": (0.0, 45.0),
    "dissolved_oxygen": (0.0, 15.0),
    "avg_dissolved_oxygen": (0.0, 15.0),
    "min_dissolved_oxygen": (0.0, 15.0),
    "max_dissolved_oxygen": (0.0, 15.0),
    "turbidity": (0.0, 200.0),
    "avg_turbidity": (0.0, 200.0),
    "water_level": (0.0, 5.0),
    "avg_water_level": (0.0, 5.0),
}


def filter_biological_outliers(
    df: pd.DataFrame,
    limits: Optional[dict] = None,
    replace_with_nan: bool = True,
) -> pd.DataFrame:
    """
    Phát hiện và lọc các giá trị đo cảm biến nằm ngoài biên sinh học an toàn ao tôm.
    
    Args:
        df: DataFrame chứa chuỗi dữ liệu telemetry.
        limits: Từ điển biên (min, max) cho từng metric. Mặc định dùng BIOLOGICAL_LIMITS.
        replace_with_nan: Nếu True, chuyển outlier thành NaN để chuẩn bị cho bước nội suy.
        
    Returns:
        DataFrame đã lọc nhiễu.
    """
    if df.empty:
        return df.copy()

    df_cleaned = df.copy()
    thresholds = limits or BIOLOGICAL_LIMITS

    outlier_counts = {}
    for column, (min_val, max_val) in thresholds.items():
        if column in df_cleaned.columns:
            is_numeric = pd.to_numeric(df_cleaned[column], errors="coerce")
            invalid_mask = (is_numeric < min_val) | (is_numeric > max_val)
            count = int(invalid_mask.sum())
            if count > 0:
                outlier_counts[column] = count
                if replace_with_nan:
                    df_cleaned.loc[invalid_mask, column] = float("nan")
                else:
                    df_cleaned[column] = is_numeric.clip(lower=min_val, upper=max_val)

    if outlier_counts:
        logger.info(f"[filter_biological_outliers] Đã phát hiện và lọc ngoại lai: {outlier_counts}")

    return df_cleaned


def clean_and_interpolate_telemetry(
    df: pd.DataFrame,
    freq: str = "15min",
    max_gap_hours: float = 2.0,
    time_col: Optional[str] = None,
) -> pd.DataFrame:
    """
    Quy trình chuẩn hóa chuỗi thời gian telemetry:
    1. Đảm bảo Index là DatetimeIndex chuẩn có bước nhảy freq đồng đều.
    2. Lọc các giá trị ngoại lai sinh học thành NaN.
    3. Nội suy tuyến tính (Linear Interpolation) cho các khoảng rớt mạng IoT (<= max_gap_hours).
    4. Cắm cờ cảnh báo nếu khoảng khuyết vượt quá ngưỡng trôi dạt max_gap_hours.
    
    Args:
        df: DataFrame đầu vào.
        freq: Tần suất đồng bộ chuỗi thời gian (mặc định: '15min').
        max_gap_hours: Giới hạn tối đa cho phép nội suy (mặc định: 2.0 giờ).
        time_col: Tên cột thời gian nếu chưa set index.
        
    Returns:
        pd.DataFrame sạch, đầy đủ chỉ số, có cờ theo dõi nội suy.
    """
    if df.empty:
        return df.copy()

    df_proc = df.copy()

    # 1. Đảm bảo DatetimeIndex
    if time_col and time_col in df_proc.columns:
        df_proc[time_col] = pd.to_datetime(df_proc[time_col], utc=True)
        df_proc.set_index(time_col, inplace=True)
    elif not isinstance(df_proc.index, pd.DatetimeIndex):
        try:
            df_proc.index = pd.to_datetime(df_proc.index, utc=True)
        except Exception as e:
            logger.error(f"[clean_and_interpolate_telemetry] Index không thể chuyển thành DatetimeIndex: {e}")
            raise ValueError(f"DataFrame index phải là DatetimeIndex: {e}")

    df_proc.sort_index(inplace=True)

    # 2. Lọc ngoại lai sinh học
    df_proc = filter_biological_outliers(df_proc, replace_with_nan=True)

    # 3. Đồng bộ lưới thời gian (Reindex/Resample đều đặn)
    full_idx = pd.date_range(start=df_proc.index.min(), end=df_proc.index.max(), freq=freq)
    df_reindexed = df_proc.reindex(full_idx)

    # Giữ lại pond_id nếu có
    if "pond_id" in df_proc.columns:
        first_valid_pond = df_proc["pond_id"].dropna().iloc[0] if not df_proc["pond_id"].dropna().empty else None
        if first_valid_pond:
            df_reindexed["pond_id"] = df_reindexed["pond_id"].fillna(first_valid_pond)

    # 4. Tính toán limit steps cho nội suy tuyến tính
    # Với freq 15min -> 1 giờ = 4 bước -> 2 giờ = 8 bước
    freq_delta = pd.Timedelta(freq)
    steps_per_hour = pd.Timedelta(hours=1) / freq_delta
    limit_steps = max(1, int(round(steps_per_hour * max_gap_hours)))

    numeric_cols = df_reindexed.select_dtypes(include=["number"]).columns.tolist()

    # Đánh dấu những điểm dữ liệu vốn bị khuyết
    original_nan_mask = df_reindexed[numeric_cols].isna()

    # 5. Nội suy tuyến tính với giới hạn limit_steps
    df_interpolated = df_reindexed.copy()
    df_interpolated[numeric_cols] = df_reindexed[numeric_cols].interpolate(
        method="linear",
        limit=limit_steps,
        limit_direction="forward",
    )

    # 6. Đánh dấu cờ chất lượng dữ liệu
    # is_interpolated: True tại các điểm được bù đắp dữ liệu bằng nội suy
    interpolated_mask = original_nan_mask & (~df_interpolated[numeric_cols].isna())
    df_interpolated["is_interpolated"] = interpolated_mask.any(axis=1)

    # gap_exceeded_limit: True nếu sau khi nội suy mà vẫn còn NaN (khoảng mất tín hiệu > 2h)
    remaining_nan = df_interpolated[numeric_cols].isna().any(axis=1)
    df_interpolated["gap_exceeded_limit"] = remaining_nan

    logger.info(
        f"[clean_and_interpolate_telemetry] Tổng mẫu: {len(df_interpolated)}, "
        f"Số điểm nội suy: {int(df_interpolated['is_interpolated'].sum())}, "
        f"Số điểm vượt ngưỡng khuyết {max_gap_hours}h: {int(df_interpolated['gap_exceeded_limit'].sum())}"
    )

    return df_interpolated


# ==============================================================================
# TASK-DP-03: Trích Xuất 7 Đặc Trưng Thực Nghiệm (Feature Integrity Rule)
# ==============================================================================

REQUIRED_FEEDING_FEATURES = (
    "shrimp_age",
    "shrimp_weight",
    "do_min",
    "tan_delta",
    "rain_0600",
    "previous_feed",
    "water_exchange_ratio",
)

SQL_RECENT_TAN_LOGS = """
SELECT nh3_value, tested_at
FROM manual_test_log
WHERE pond_id = :pond_id
ORDER BY tested_at DESC
LIMIT 2;
"""


def fetch_tan_delta_from_db(
    pond_id: str,
    session: Optional[Session] = None,
) -> float:
    """
    Truy vấn 2 lần đo gần nhất từ manual_test_log để tính độ biến thiên TAN (tan_delta).
    tan_delta = tan_recent - tan_previous (mg/L).
    """
    close_session_after = False
    if session is None:
        session = SessionLocal()
        close_session_after = True

    try:
        result = session.execute(text(SQL_RECENT_TAN_LOGS), {"pond_id": pond_id})
        rows = result.fetchall()
        if len(rows) >= 2:
            tan_recent = float(rows[0][0])
            tan_prev = float(rows[1][0])
            return round(tan_recent - tan_prev, 4)
        return 0.0
    except Exception as e:
        logger.warning(f"[fetch_tan_delta_from_db Warning] Không thể lấy tan_delta cho ao {pond_id}: {e}")
        return 0.0
    finally:
        if close_session_after:
            session.close()


def extract_do_min_from_telemetry(
    df_telemetry: pd.DataFrame,
    window_hours: int = 12,
    do_column: str = "avg_dissolved_oxygen",
) -> float:
    """
    Trích xuất giá trị DO tối thiểu (do_min) trong cửa sổ window_hours gần nhất.
    """
    if df_telemetry.empty:
        return 5.0  # Mặc định an toàn nếu không có dữ liệu

    col = do_column if do_column in df_telemetry.columns else "dissolved_oxygen"
    if col not in df_telemetry.columns:
        return 5.0

    series = df_telemetry[col].dropna()
    if series.empty:
        return 5.0

    # Lấy cửa sổ thời gian gần nhất
    if isinstance(df_telemetry.index, pd.DatetimeIndex):
        latest_time = df_telemetry.index.max()
        cutoff_time = latest_time - pd.Timedelta(hours=window_hours)
        window_series = series[series.index >= cutoff_time]
        if not window_series.empty:
            return float(window_series.min())

    # Fallback lấy N mẫu gần nhất
    steps = window_hours * 4
    return float(series.tail(steps).min())


def build_feeding_feature_dict(
    shrimp_age: float,
    shrimp_weight: float,
    do_min: float,
    tan_delta: float,
    rain_0600: float,
    previous_feed: float,
    water_exchange_ratio: float,
) -> dict:
    """
    Đóng gói và kiểm tra tính toàn vẹn của 7 biến thực nghiệm bắt buộc.
    
    Quy tắc Feature Integrity: Tuyệt đối không lược bỏ biến nào trong 7 biến thực nghiệm.
    """
    features = {
        "shrimp_age": float(shrimp_age),
        "shrimp_weight": float(shrimp_weight),
        "do_min": float(do_min),
        "tan_delta": float(tan_delta),
        "rain_0600": float(rain_0600),
        "previous_feed": float(previous_feed),
        "water_exchange_ratio": float(water_exchange_ratio),
    }

    # Xác thực sinh học cơ bản
    if features["shrimp_age"] < 1:
        raise ValueError("shrimp_age phải >= 1 ngày.")
    if features["shrimp_weight"] <= 0:
        raise ValueError("shrimp_weight phải > 0 g/con.")
    if features["rain_0600"] < 0:
        raise ValueError("rain_0600 không được âm.")
    if features["previous_feed"] < 0:
        raise ValueError("previous_feed không được âm.")
    if not (0 <= features["water_exchange_ratio"] <= 100):
        raise ValueError("water_exchange_ratio phải nằm trong khoảng [0, 100]%.")

    return features


def extract_features_from_pond_state(
    pond_id: str,
    shrimp_age: float,
    shrimp_weight: float,
    rain_0600: float,
    previous_feed: float,
    water_exchange_ratio: float,
    df_telemetry: Optional[pd.DataFrame] = None,
    tan_delta: Optional[float] = None,
    session: Optional[Session] = None,
) -> dict:
    """
    Tổng hợp đầy đủ 7 biến thực nghiệm từ dữ liệu ao, cảm biến telemetry và nhật ký đo kiểm.
    """
    # 1. Tính do_min từ telemetry (nếu được cung cấp)
    if df_telemetry is not None and not df_telemetry.empty:
        computed_do_min = extract_do_min_from_telemetry(df_telemetry, window_hours=12)
    else:
        computed_do_min = 5.0

    # 2. Tính tan_delta từ database nếu chưa truyền trực tiếp
    if tan_delta is None:
        computed_tan_delta = fetch_tan_delta_from_db(pond_id, session=session)
    else:
        computed_tan_delta = float(tan_delta)

    return build_feeding_feature_dict(
        shrimp_age=shrimp_age,
        shrimp_weight=shrimp_weight,
        do_min=computed_do_min,
        tan_delta=computed_tan_delta,
        rain_0600=rain_0600,
        previous_feed=previous_feed,
        water_exchange_ratio=water_exchange_ratio,
    )


# ==============================================================================
# TASK-DP-04: Phân Chia Time-Blocked / TimeSeriesSplit & StandardScaler Chống Rò Rỉ
# ==============================================================================

from pathlib import Path
from typing import Generator, List, Tuple
import joblib
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler


class TimeSeriesDataPipeline:
    """
    Pipeline tiền xử lý dữ liệu và phân chia tập dữ liệu chuỗi thời gian.
    Tuân thủ tuyệt đối Anti-Data Leakage Rule:
    - Không shuffle ngẫu nhiên dữ liệu chuỗi thời gian.
    - StandardScaler chỉ được phép khớp (fit) trên tập Train.
    - Tập Test chỉ được phép transform dựa trên scaler đã fit từ Train.
    """

    def __init__(
        self,
        feature_cols: Sequence[str] = REQUIRED_FEEDING_FEATURES,
        target_col: str = "feed_amount_kg",
        scaler_path: str = "trained_models/feeding_scaler.joblib",
    ):
        self.feature_cols = list(feature_cols)
        self.target_col = target_col
        self.scaler_path = Path(scaler_path)
        self.scaler: Optional[StandardScaler] = None

    def prepare_time_blocked_split(
        self,
        df: pd.DataFrame,
        test_ratio: float = 0.20,
        save_scaler: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, StandardScaler]:
        """
        Phân chia tập dữ liệu theo khối thời gian (Time-Blocked Split):
        - Đoạn đầu [0 -> T_split] là tập Train.
        - Đoạn cuối [T_split -> T_end] là tập Test.
        
        Quy tắc Anti-Data Leakage:
        - scaler.fit_transform(X_train)
        - scaler.transform(X_test)
        """
        if df.empty:
            raise ValueError("DataFrame đầu vào rỗng, không thể phân chia dữ liệu.")

        for col in self.feature_cols:
            if col not in df.columns:
                raise ValueError(f"Thiếu đặc trưng bắt buộc: '{col}'. Danh sách yêu cầu: {self.feature_cols}")

        if self.target_col not in df.columns:
            raise ValueError(f"Thiếu biến mục tiêu: '{self.target_col}'")

        n_samples = len(df)
        split_idx = int(n_samples * (1.0 - test_ratio))

        if split_idx <= 0 or split_idx >= n_samples:
            raise ValueError(f"Tỷ lệ test_ratio={test_ratio} không hợp lệ với n_samples={n_samples}")

        # Tách dữ liệu theo đúng trật tự thời gian
        train_df = df.iloc[:split_idx]
        test_df = df.iloc[split_idx:]

        X_train_raw = train_df[self.feature_cols].to_numpy(dtype=np.float64)
        y_train = train_df[self.target_col].to_numpy(dtype=np.float64)

        X_test_raw = test_df[self.feature_cols].to_numpy(dtype=np.float64)
        y_test = test_df[self.target_col].to_numpy(dtype=np.float64)

        # Anti-Data Leakage: Fit CHỈ trên train set
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train_raw)
        X_test_scaled = self.scaler.transform(X_test_raw)

        if save_scaler:
            self.save_scaler()

        logger.info(
            f"[prepare_time_blocked_split] Train: {X_train_scaled.shape[0]} mẫu, "
            f"Test: {X_test_scaled.shape[0]} mẫu (test_ratio={test_ratio:.1%}). Scaler đã lưu."
        )

        return X_train_scaled, y_train, X_test_scaled, y_test, self.scaler

    def get_rolling_origin_folds(
        self,
        df: pd.DataFrame,
        n_splits: int = 5,
    ) -> Generator[Tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray, StandardScaler], None, None]:
        """
        Tạo các fold kiểm định chéo theo nguyên lý Rolling-Origin (TimeSeriesSplit).
        Trong từng fold, StandardScaler được khởi tạo mới và chỉ fit trên tập train của fold đó.
        """
        if len(df) < n_splits + 1:
            raise ValueError(f"Số lượng mẫu ({len(df)}) quá nhỏ so với số fold n_splits={n_splits}")

        X_raw = df[self.feature_cols].to_numpy(dtype=np.float64)
        y = df[self.target_col].to_numpy(dtype=np.float64)

        tscv = TimeSeriesSplit(n_splits=n_splits)

        for fold, (train_indices, test_indices) in enumerate(tscv.split(X_raw), 1):
            X_tr = X_raw[train_indices]
            y_tr = y[train_indices]
            X_te = X_raw[test_indices]
            y_te = y[test_indices]

            fold_scaler = StandardScaler()
            X_tr_scaled = fold_scaler.fit_transform(X_tr)
            X_te_scaled = fold_scaler.transform(X_te)  # CHỈ TRANSFORM!

            logger.debug(
                f"[TimeSeriesSplit Fold {fold}] Train size: {len(train_indices)}, Test size: {len(test_indices)}"
            )

            yield fold, X_tr_scaled, y_tr, X_te_scaled, y_te, fold_scaler

    def save_scaler(self, path: Optional[Union[str, Path]] = None) -> Path:
        """Lưu StandardScaler đã fit vào tệp .joblib"""
        if self.scaler is None:
            raise ValueError("Scaler chưa được khớp (fit) dữ liệu, không thể lưu.")

        save_to = Path(path) if path else self.scaler_path
        save_to.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.scaler, save_to)
        logger.info(f"[TimeSeriesDataPipeline] Đã lưu StandardScaler vào: {save_to}")
        return save_to

    def load_scaler(self, path: Optional[Union[str, Path]] = None) -> StandardScaler:
        """Đọc StandardScaler từ tệp .joblib"""
        load_from = Path(path) if path else self.scaler_path
        if not load_from.exists():
            raise FileNotFoundError(f"Không tìm thấy file scaler tại: {load_from}")

        self.scaler = joblib.load(load_from)
        logger.info(f"[TimeSeriesDataPipeline] Đã nạp StandardScaler từ: {load_from}")
        return self.scaler
