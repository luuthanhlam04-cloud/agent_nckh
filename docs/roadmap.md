# Digital Scholar Roadmap & Milestones

Tài liệu theo dõi lộ trình phát triển của hệ thống **Digital Scholar (Personal Research Cockpit)**.

---

## 1. MILESTONES & SPRINT HISTORY

### Sprint 1: Foundation & Voice Pipeline (Completed)
- [x] Tích hợp Gemini Live STT / Gemini Flash STT in-memory PCM streaming.
- [x] Cơ chế CancelToken hỗ trợ ngắt luồng thu âm ngay lập tức.
- [x] Zero-latency streaming từ microphone qua PyAudio.

### Sprint 2: Storage & Clean Architecture Refactoring (Completed)
- [x] Phân tầng Clean Architecture: Domain, Application, Infrastructure, Presentation.
- [x] Thay thế biến toàn cục bằng Dependency Injection tại `main.py`.
- [x] Cấu hình Qdrant local vector store và Neo4j cloud graph store.
- [x] Bộ kiểm tra quy tắc mã nguồn AST Linter (Tier A, Tier B, Tier C).

### Sprint 3: Academic Ingestion & Heading-Aware Parsing (Completed)
- [x] Tích hợp PyMuPDF trích xuất font metadata và phát hiện Section headings.
- [x] Parent-Child chunking (Chunk cha bao quát trang, Chunk con chứa đoạn văn micro).
- [x] Watchdog listener giám sát ngầm thư mục `01_Inbox/` không làm đơ giao diện.

### Sprint 4: Spotlight UI & Daily Desktop Assistant (Completed)
- [x] Giao diện PyQt6 Spotlight kích hoạt bằng phím tắt toàn cục `Ctrl + Space` / `Alt + Space`.
- [x] Tích hợp `SemanticInterceptor` với tập neo embedding e5-base xử lý các lệnh Desktop nhanh ($0 API).
- [x] Điều khiển hệ thống Windows: Âm lượng, khởi chạy ứng dụng, mở YouTube, kiểm tra thời gian.

### Sprint 5 (V6.0): Personal Research Cockpit & Dual-Write Architecture (Completed & Verified)
- [x] **Hybrid Intent Sniffer & Vietnamese Stopword Stripper:**
  - Lọc sạch 100% từ đệm văn nói (`Ờ... mở giùm tao cái... bài gì của Sơn Tùng ấy trên YouTube đi` $\rightarrow$ `Sơn Tùng`).
  - Fallback Graceful Degradation: Tự động hỏi lại khi slot rỗng.
- [x] **Silero VAD (ONNX Local) - Hands-free Voice Mode:**
  - Mô hình neural network <2MB chạy CPU local, thay thế hoàn toàn thuật toán RMS cũ.
  - Pre-speech Ring Buffer (500ms) chống mất phụ âm đầu câu.
  - Trailing Silence (1.5s) tự động đóng gói buffer gửi sang STT.
- [x] **Failover LLM Client & Cost Guard:**
  - Tự động chuyển vùng dự phòng từ OpenRouter sang Gemini Direct trên các mã lỗi HTTP 402/403/429.
  - Ngăn chặn triệt để sự cố cạn kiệt quota và tối ưu chi phí còn $1 - $3/tháng.
- [x] **Dual-Write Architecture (Qdrant + Neo4j):**
  - Đồng bộ song song Vector Chunks vào Qdrant và Cây cấu trúc vật lý (`:Paper -> :Section -> :Chunk`) vào Neo4j với chi phí $0 API.
  - Giải quyết dứt điểm Bẫy tái chỉ mục (Re-indexing Trap).
- [x] **Socratic Thought Partner & Obsidian Research Journal:**
  - Chêm gợi ý phản biện học thuật Socratic khi tra cứu nghiên cứu.
  - Ghi nhận các điểm nghẽn (Research Gaps) vào `Obsidian_Vault/05_Research_Journal/YYYY-MM-DD.md`.
- [x] **Kiểm thử toàn diện 71/71 tests (51 integration tests + 20 unit tests) đạt 100% Pass Rate.**

---

## 2. FUTURE DIRECTIONS

- [ ] **Offline Local LLM Fallback (Qwen 2.5 / DeepSeek R1 Distill):** Tích hợp Ollama/vLLM local khi máy tính ngắt mạng internet hoàn toàn.
- [ ] **Vision Chart & Diagram Extraction:** Sử dụng Gemini Vision phân tích biểu đồ tọa độ, kiến trúc và hình ảnh minh họa trong bài báo.
- [ ] **Multi-paper Cross-graph Reasoning:** Mở rộng Phase 4 Semantic Extraction để phát hiện các mối quan hệ `(:Method)-[:CONTRADICTS]->(:Method)` giữa nhiều tài liệu khác nhau.
