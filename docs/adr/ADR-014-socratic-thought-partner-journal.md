# ADR-014: Đối tác Tư duy Phản biện Socratic & Nhật ký Nghiên cứu Obsidian

- **Trạng thái:** Accepted
- **Ngày:** 2026-11-13
- **Tác giả:** Lead Agentic Systems Architect

---

## 1. Ngữ cảnh (Context)
Yêu cầu cốt lõi của tác giả dự án:
*"Không phải kiểu agent suy nghĩ thay tôi mà là hỗ trợ tôi phân tích để từ đó tôi mò ra được các vấn đề, điểm nghẽn mà triển khai... autonomic kiểu biểu diễn tri thức hơn chứ không phải bị động hỏi gì nói nấy."*
Nếu Agent tự ý hiển thị popup thông báo ngoài màn hình khi phát hiện điểm nghẽn sẽ gây phiền toái (Bloatware/Spam). Ngược lại, nếu chỉ chờ người dùng hỏi gì trả lời nấy sẽ biến hệ thống thành một chatbot thông thường.

---

## 2. Quyết định (Decision)
Triển khai mô hình cân bằng 2 kênh:
1. **Kênh ngầm (Asynchronous Research Journaling):**
   - Tạo service `ResearchJournalService` ghi nhận các lỗ hổng nghiên cứu (Research Gaps), giả định ngầm và rủi ro phương pháp vào file Markdown:
     `Obsidian_Vault/05_Research_Journal/YYYY-MM-DD.md`.
   - Tiến trình này diễn ra âm thầm, không ngắt quãng luồng làm việc của người dùng.
2. **Kênh nổi (Just-in-Time Socratic Injection):**
   - Khi người dùng chủ động truy vấn về các chủ đề nghiên cứu (Paper, RAG, Thuật toán) trong Spotlight UI, `RequestCoordinator` tự động chêm vào lời gợi ý phản biện Socratic:
     > *"💡 Gợi ý phản biện học thuật: Phương pháp trên có phụ thuộc vào giả định ngầm nào không? Điểm nghẽn lớn nhất khi áp dụng vào thực tế là gì?"*

---

## 3. Hệ quả (Consequences)
- **Ưu điểm:**
  - Kích thích tư duy độc lập của nhà nghiên cứu, biến Agent thành một "Thought Partner".
  - Tích hợp tự nhiên với hệ sinh thái Obsidian Vault sẵn có của người dùng.

