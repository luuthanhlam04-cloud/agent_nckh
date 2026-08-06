# Processing Pipelines Details

Tài liệu này lưu trữ các thông số kỹ thuật nội bộ (Implementation Details) của các luồng xử lý chính trong Digital Scholar.

## 1. Parent-Child Chunking
- Parent chunk: Đoạn văn bản chứa ~600 ký tự.
- Child chunk: Nhỏ hơn, tối ưu để tạo Vector nhúng. Có chứa trường `parent_id`.
- Khi search: Tìm Child -> Trả về Parent.

## 2. Voice Pipeline
- Không lưu file đệm trên ổ cứng. Sử dụng raw PCM bytes (16kHz).
- Đẩy trực tiếp qua đường truyền HTTP lên Gemini API.
