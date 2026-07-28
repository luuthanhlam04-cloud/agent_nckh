# Architecture Principles

> **Tầng:** Foundation của mọi quyết định thiết kế.  
> **Đối tượng:** Mọi developer và AI agent đóng góp vào dự án.

---

## 1. Layer Model

Digital Scholar tuân thủ **Layered Architecture** với dependency hướng xuống Foundation:

```
Presentation    (src/ui/)           ← Cao nhất
     ↓
Infrastructure  (src/db/)
     ↓
Application     (src/core/, src/services/)
     ↓
Domain          (src/core/interfaces.py)
     ↓
Foundation      (src/shared/, src/utils/)   ← KHÔNG import layer nào
```

### Quy tắc bắt buộc (Tier A — vi phạm = CI FAIL)

| Quy tắc | Hậu quả nếu vi phạm |
|---------|---------------------|
| Foundation không được import bất kỳ layer nào | Circular dependency, import loop |
| Infrastructure không được import Presentation | Kiến trúc đảo ngược, không test được |
| Application không được import Infrastructure trực tiếp — phải qua Domain interfaces | Tight coupling, không thể thay implementation |

### Layer Map (dùng cho AST dependency check)

```python
LAYER_ORDER = {
    "src/ui":       4,   # Presentation
    "src/db":       3,   # Infrastructure
    "src/core":     2,   # Application
    "src/services": 2,   # Application
    "src/utils":    0,   # Foundation (cross-cutting)
    "src/shared":   0,   # Foundation (cross-cutting)
}
```

---

## 2. Interface Rule — Rule of Two

> **Chỉ tạo interface khi đã có 2 implementation HOẶC chắc chắn sắp có implementation thứ hai.**

Mục tiêu: tránh over-engineering với abstraction không cần thiết.

| Interface | Sprint tạo | Lý do |
|-----------|-----------|-------|
| `IKnowledgeStore` | Sprint 2 | Qdrant + Neo4j cần cùng interface |
| `ILLMClient` | Sprint 2 | Gemini + OpenRouter song song |
| `IParser` | Sprint 4 | PDFParser + NCKHParser sắp đến |
| `IRetriever` | Sprint 5 | HybridRAG + NCKHRetriever so sánh |
| `IEmbedder` | Defer | Chỉ 1 model trong 2 năm đầu |

---

## 3. Dependency Injection

Mọi class nhận dependency qua constructor — không tự khởi tạo Infrastructure bên trong:

```python
# Đúng:
class ReActOrchestrator:
    def __init__(self, hybrid_rag: IKnowledgeStore, worker: ILLMClient): ...

# Sai:
class ReActOrchestrator:
    def __init__(self):
        self._rag = QdrantManager()   # Hard-coded dependency
```

Tất cả `new` (khởi tạo object) phải tập trung tại `main.py`.

---

## 4. Configuration

- `os.getenv()` chỉ được gọi tại `src/shared/config.py`
- Validation (raise nếu thiếu key) tại `src/shared/settings.py`
- `main.py` gọi `settings.validate()` trước bất kỳ thứ gì khác

---

## 5. PromptBuilder

Tất cả prompt template phải nằm trong `src/core/prompt_builder.py`.

Nghiêm cấm hardcode prompt string trong:
- `orchestrator.py`
- `memory_consolidator.py`
- `docx_exporter.py`
- `parser.py`

---

## 6. Docs Structure

```
docs/
├── engineering/
│   ├── architecture.md   ← File này
│   ├── threading.md      ← Multi-threading rules
│   ├── coding.md         ← Coding standards + 3-tier rule system
│   └── testing.md        ← production_check, run_tests
├── adr/                  ← Architecture Decision Records
└── roadmap.md            ← Sprint plan
```
