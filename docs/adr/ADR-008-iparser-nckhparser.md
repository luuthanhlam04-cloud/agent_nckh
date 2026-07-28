# ADR-008: IParser — Chuẩn bị slot cho NCKHParser

## Trạng thái: Accepted

## Bối cảnh
Dự án cần hỗ trợ trích xuất nội dung từ nhiều định dạng tài liệu khác nhau (PDF, PPTX) và sắp tới là bộ parser đặc thù cho đề tài NCKH (Sprint 5). Nếu cứ tiếp tục viết các hàm parse rời rạc (`pdf_parser`, `pptx_parser`) và dùng lệnh `if/else` để gọi, hệ thống sẽ vi phạm nguyên lý Open/Closed (OCP) và trở nên khó bảo trì.

## Quyết định
Áp dụng **Rule of Two** (đã có PDF và PPTX, và chuẩn bị có cái thứ 3) để tạo ra Interface Layer:
1. Định nghĩa `IParser` trong `src/core/interfaces.py` với 2 method: `parse()` và `supported_extensions()`.
2. Áp dụng cho các parser hiện tại: `PDFParser(IParser)` và `PPTXParser(IParser)`.
3. Xây dựng `ParserRegistry` để tự động map định dạng file (ví dụ `.pdf`) với instance parser tương ứng.

## Hậu quả
### Tích cực
- **Tuân thủ OCP**: Khi phát triển `NCKHParser` ở Sprint 5, chỉ cần viết class kế thừa `IParser` và gọi `ParserRegistry.register()`, không cần sửa bất kỳ đoạn code hiện tại nào.
- Code gọn gàng, decoupling hoàn toàn lớp infrastructure (parsers) khỏi lớp application.

### Tiêu cực / Trade-off
- Thêm một tầng trừu tượng (registry) có thể hơi "over-engineering" đối với các dự án nhỏ, nhưng cần thiết cho lộ trình của dự án nghiên cứu khoa học.
