# ADR-012: Kiến trúc Dual-Write Đồng bộ Cây Cấu trúc Vật lý vào Neo4j

- **Trạng thái:** Accepted
- **Ngày:** 2026-11-13
- **Tác giả:** Lead Agentic Systems Architect

---

## 1. Ngữ cảnh (Context)
Trong các cuộc thảo luận kiến trúc, có đề xuất trì hoãn tích hợp Neo4j Graph Database sang Phase 4 và chỉ dùng Qdrant ở các Phase đầu.
Tuy nhiên, phản biện kiến trúc đã chỉ ra **Bẫy tái chỉ mục (Re-indexing Trap)**:
- Nếu người dùng nạp hàng trăm bài báo khoa học vào Qdrant trong nhiều tháng, việc đưa Neo4j vào ở Phase 4 sẽ buộc hệ thống phải parse và embed lại toàn bộ các file PDF từ đầu, gây lãng phí tài nguyên và có nguy cơ đứt gãy liên kết ID.
- Mặt khác, nếu dùng LLM để trích xuất ngữ nghĩa sâu ngay từ đầu sẽ gây bùng nổ chi phí API không cần thiết.

---

## 2. Quyết định (Decision)
Triển khai mô hình **Dual-Write Architecture** phân tầng:
1. **Phase 1 ($0 API, Deterministic Rule-based):**
   - Khi tài liệu được thả vào `01_Inbox/`, parser bóc tách cây cấu trúc hình thức:
     `(:Paper)-[:HAS_SECTION]->(:Section)-[:HAS_CHUNK]->(:Chunk)`.
   - Vector chunks được lưu vào **Qdrant Local** và trả về danh sách UUIDs.
   - Các UUID này được lưu trữ trực tiếp trên thuộc tính `qdrant_chunk_ids` của node `:Chunk` và `:Section` trong Neo4j.
2. **Phase 4 (Semantic Enrichment):**
   - Khi cần trích xuất các quan hệ ngữ nghĩa sâu (`:Method`, `:Concept`, `:Problem`), LLM chỉ việc đọc text trực tiếp từ các chunk đã có trong Qdrant/SQLite để bổ sung cạnh vào Neo4j mà **không cần mở lại file PDF hay re-index lại từ đầu**.

---

## 3. Hệ quả (Consequences)
- **Ưu điểm:**
  - Hoàn toàn bẻ gãy Bẫy tái chỉ mục (Re-indexing Trap).
  - Chi phí API ở Phase 1 là **$0** (chạy bằng regex và cấu trúc đề mục).
  - Có cơ chế Graceful Degradation: nếu Neo4j offline, hệ thống vẫn lưu vào Qdrant bình thường mà không bị crash.

