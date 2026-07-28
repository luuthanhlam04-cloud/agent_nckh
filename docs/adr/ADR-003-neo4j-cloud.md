# ADR-003: Neo4j Aura Cloud thay vì Neo4j Local

**Trạng thái:** Accepted  
**Ngày:** 2026-07  
**Sprint:** V3.x

---

## Bối cảnh

Cần graph database cho GraphRAG (entity và relationship storage). Lựa chọn:
- **Neo4j Desktop/Local**: cài trên máy, cần Docker hoặc installer
- **Neo4j Aura Free Tier**: cloud-managed, miễn phí, không cần infrastructure

## Quyết định

Dùng **Neo4j Aura Free Tier** (cloud).

## Lý do

1. **Zero infrastructure overhead:** Dự án là research tool, không phải production service. Tránh cài thêm Docker/Neo4j Desktop trên máy development.

2. **Free tier đủ dùng:** Aura Free cung cấp 1 instance miễn phí với 50K nodes / 175K relationships — đủ cho nghiên cứu với vài trăm paper.

3. **Consistency:** Qdrant đã chạy embedded local. Neo4j cloud → hệ thống hybrid: local vector store + cloud graph store.

## Hậu quả

### Tích cực
- Không cần cài thêm phần mềm
- Managed service (backup, update tự động)

### Tiêu cực / Trade-off
- Phụ thuộc internet (nhưng đã có dependency này)
- Free tier có giới hạn storage và connection
- Latency Neo4j query cao hơn local (~100-200ms vs ~10ms)

## Trạng thái implementation

> ⚠️ Entity extraction chưa được implement (defer đến Sprint 6).  
> Neo4j hiện tại đã kết nối nhưng graph rỗng — đây là quyết định có chủ ý, không phải bug.
