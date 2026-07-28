# Digital Scholar — Development Roadmap

> Xem chi tiết từng Sprint tại: [Implementation Plan](../../.gemini/... )  
> Tài liệu kiến trúc: [docs/engineering/architecture.md](engineering/architecture.md)

---

## Sprint 0 — Governance Foundation ✅
**Trạng thái:** Completed

- Engineering Handbook (`docs/`)
- Architecture Decision Records (`docs/adr/`)
- Modular linter (`rules/` — Tier A/B/C)
- `production_check.py` v2.0 (categorized output)

---

## Sprint 1 — Architecture Core
**Trạng thái:** In Progress

**Mục tiêu:** Xóa duplicate logic, PromptBuilder tập trung prompt, Coordinator tách main.py

| File | Thay đổi |
|------|---------|
| `src/core/orchestrator_config.py` | [NEW] RetrieveConfig, GenerateConfig, preset configs |
| `src/core/orchestrator.py` | [MODIFY] _node_retrieve/generate nhận config |
| `src/core/prompt_builder.py` | [NEW] PromptBuilder class — tập trung 4 prompt sources |
| `src/core/coordinator.py` | [NEW] RequestCoordinator |
| `main.py` | [MODIFY] Pure bootstrap — chỉ boot + DI |

**Deliverable:** AI nhớ hội thoại. Prompts tập trung 1 nơi. Hết ~60 dòng duplicate.

---

## Sprint 2 — Modularization
**Trạng thái:** Pending Sprint 1

**Mục tiêu:** Interface Layer (Rule of Two), tách Workers, Constructor Injection

| File | Thay đổi |
|------|---------|
| `src/core/interfaces.py` | [NEW] IKnowledgeStore, ILLMClient |
| `src/ui/workers.py` | [NEW] Tách 4 Workers khỏi spotlight.py |
| `src/db/hybrid_rag.py` | [MODIFY] QdrantManager implements IKnowledgeStore |
| `src/core/orchestrator.py` | [MODIFY] Constructor Injection |

**Deliverable:** Unit test không cần Qdrant thật. Dependency Direction check active.

---

## Sprint 3 — Production Hardening
**Trạng thái:** Pending Sprint 2

**Mục tiêu:** Metrics với Correlation ID, Config validation, Logging chuẩn hóa

| File | Thay đổi |
|------|---------|
| `src/shared/metrics.py` | [NEW] PipelineMetrics + timed() context manager |
| `src/shared/config.py` | [NEW] Tập trung os.getenv() |
| `src/shared/settings.py` | [NEW] validate() — fail fast nếu thiếu API key |
| `src/db/hybrid_rag.py` | [MODIFY] Cleanup: comment, GC, constant |

**Deliverable:** Log metrics mỗi request. Config validate khi boot. Benchmark được.

---

## Sprint 4 — Open-source Abstraction
**Trạng thái:** Pending Sprint 3

**Mục tiêu:** IParser interface (slot cho NCKHParser), LLM abstraction

| File | Thay đổi |
|------|---------|
| `src/core/interfaces.py` | [MODIFY] Thêm IParser |
| `src/utils/parser.py` | [MODIFY] PDFParser, PPTXParser implement IParser |
| `src/infrastructure/llm/` | [NEW] OpenRouterLLMClient, GeminiLLMClient |

**Deliverable:** Thêm NCKHParser chỉ cần viết class + register. LLM swap dễ dàng.

---

## Sprint 5 — NCKH Parser
**Trạng thái:** Pending Sprint 4

- NCKHParser(IParser) theo thuật toán đề tài
- IRetriever interface
- Benchmark vs PDFParser với Metrics

---

## Sprint 6 — NCKH HybridRAG
**Trạng thái:** Pending Sprint 5

- Neo4j entity extraction (V7 — Roadmap, không phải bug)
- NCKHRetriever(IRetriever)
- Benchmark vs HybridRAGRetriever

---

## Kiến trúc tương lai (Post-Sprint 6)

- Event Bus (nếu plugin architecture cần)
- Vision module (camera input)
- Scheduler (scheduled tasks)
- Local LLM (OllamaLLMClient)
- Plugin system
