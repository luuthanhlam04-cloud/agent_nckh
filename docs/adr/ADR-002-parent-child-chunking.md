# ADR-002: Parent-Child Chunking Strategy

**Trạng thái:** Accepted  
**Ngày:** 2026-07  
**Sprint:** V3.x

---

## Bối cảnh

Cần quyết định cách chia nhỏ tài liệu PDF/PPTX để lưu vào Qdrant vector database. Hai approach:
- **Fixed-size chunking**: chia theo số token cố định
- **Parent-Child chunking**: chunk nhỏ để search, chunk lớn để context

## Quyết định

Áp dụng **Parent-Child chunking** với:
- Child chunk: ~150-200 chars — đơn vị search (vector đặc trưng hơn)
- Parent chunk: ~600 chars — đơn vị context (đủ ngữ cảnh cho LLM)

## Lý do

1. **Search accuracy vs Context quality trade-off:** Child chunk nhỏ → vector embedding đặc trưng hơn → cosine similarity chính xác hơn. Nhưng nếu chỉ cho LLM đọc chunk nhỏ → thiếu context.

2. **Standard practice:** Đây là pattern chuẩn trong production RAG systems (LangChain, LlamaIndex đều implement tương tự).

3. **Heading-awareness:** Parser phát hiện heading qua font size median → chunk boundary không cắt ngang section → context coherent hơn.

## Hậu quả

### Tích cực
- Vector search chính xác hơn (child nhỏ, đặc trưng)
- LLM nhận đủ context (parent lớn)
- Section boundary được tôn trọng

### Tiêu cực / Trade-off
- Lưu nhiều hơn 2x dữ liệu vào Qdrant (parent + child)
- Logic ingest phức tạp hơn (phải maintain parent_id)
- Prefix bắt buộc: `"passage: "` khi ingest, `"query: "` khi search (multilingual-e5-base spec)
