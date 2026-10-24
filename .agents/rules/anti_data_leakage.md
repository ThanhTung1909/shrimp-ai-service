# Anti-Data Leakage Rule (Quy Tắc Chống Rò Rỉ Dữ Liệu)

1. Tuyệt đối KHÔNG sử dụng `train_test_split` ngẫu nhiên trên dữ liệu cảm biến chuỗi thời gian (time-series).
2. Bắt buộc áp dụng Rolling-origin Cross-validation (`TimeSeriesSplit`) hoặc Time-blocked Split.
3. `StandardScaler` và các bộ chuẩn hóa/tiền xử lý chỉ được phép khớp (fit) trên tập huấn luyện (`train set`).
4. Tập kiểm thử và tập validation chỉ được phép dùng `transform()` dựa trên các tham số đã fit từ tập train, nhằm loại bỏ hoàn toàn việc thông tin phân phối tương lai rò rỉ vào mô hình.
