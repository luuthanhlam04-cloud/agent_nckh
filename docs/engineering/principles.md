# Engineering Principles & Rule Engine

## 1. Dependency Direction
Layer cấp cao (Core) không được import layer cấp thấp (UI, DB).
Trạng thái vi phạm sẽ bị `production_check.py` báo cáo lỗi (Exit 1).

## 2. Fail Fast
Sử dụng pydantic settings. Khởi động sẽ crash ngay lập tức nếu thiếu `GEMINI_API_KEY`, thay vì đợi đến lúc user query.
