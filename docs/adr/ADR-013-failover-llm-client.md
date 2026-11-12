# ADR-013: Bộ Điều phối LLM Dự phòng Tự động (FailoverLLMClient)

- **Trạng thái:** Accepted
- **Ngày:** 2026-11-13
- **Tác giả:** Lead Agentic Systems Architect

---

## 1. Ngữ cảnh (Context)
Trong quá trình vận hành thực tế, file nhật ký hệ thống `agent.log` đã ghi nhận sự cố:
`OpenRouter Error: Key limit exceeded (HTTP 402 / 403 / 429)`.
Khi chỉ sử dụng một provider duy nhất (OpenRouter), bất kỳ sự cố nào về hạn ngạch token, thanh toán hoặc mạng đều khiến toàn bộ tiến trình sinh câu trả lời của Agent bị sập, làm gián đoạn trải nghiệm của người dùng.

---

## 2. Quyết định (Decision)
1. Xây dựng lớp trung gian `FailoverLLMClient` kế thừa `ILLMClient`.
2. Bọc 2 động cơ suy luận:
   - **Primary Engine:** OpenRouter (cho các mô hình nghiên cứu sâu).
   - **Secondary Engine:** Gemini Direct SDK (`gemini-2.5-flash`).
3. Tự động bắt các mã lỗi hạn ngạch và ngoại lệ mạng từ Primary Engine. Khi phát hiện lỗi, client lập tức yield thông báo chuyển tiếp và tự động gọi sang Secondary Engine trong vòng 100ms.

---

## 3. Hệ quả (Consequences)
- **Ưu điểm:**
  - Độ sẵn sàng (High Availability) cao: Agent không bao giờ bị đứng hình khi một provider hết quota.
  - Phân tầng chi phí: Mặc định tác vụ thông thường và ingestion sử dụng model Flash giá siêu rẻ ($0.075 / 1M tokens), đưa chi phí hàng tháng về mức $1 - $3.
- **Tuân thủ Clean Architecture:**
  - `FailoverLLMClient` độc lập với giao diện, được inject tại `main.py` tuân thủ nguyên lý Dependency Inversion.

