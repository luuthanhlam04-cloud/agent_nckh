# Testing & Quality Assurance

---

## production_check.py — Static Analysis (Tier A/B/C)

Chạy trước mỗi commit:

```bash
python production_check.py
```

### Cấu trúc rules/ module

```
rules/
├── base.py               ← RuleViolation, Severity, BaseRule
├── dependency_map.py     ← LAYER_ORDER constant
├── tier_a_safety.py      ← FAIL rules: Sleep, UIImport, DepDirection, Circular
├── tier_b_quality.py     ← FAIL/WARN: BareExcept, LongFunction, GodFile, Config
├── tier_c_convention.py  ← WARN/INFO: Naming conventions
└── metrics_checks.py     ← INFO: TypeHint, PublicAPI
```

### Output format

```
══════════════════════════════════════════
  TIER A — ARCHITECTURE SAFETY
══════════════════════════════════════════
❌ FAIL  src/ui/spotlight.py:423 [SleepBan]
         time.sleep() on Main Thread
         WHY: Qt Event Loop blocks → "Not Responding"
```

### Exit codes

| Code | Nghĩa |
|------|-------|
| 0 | Tất cả PASS |
| 1 | Có ít nhất 1 Tier A FAIL |
| 0 | Chỉ có WARN/INFO (không block) |

---

## run_tests.py — Dynamic Tests

Chạy sau production_check.py (chỉ khi linter PASS):

```bash
python run_tests.py
```

### Test categories

| Category | Mô tả |
|---------|-------|
| Unit tests | Test từng class độc lập với Mock dependencies |
| Integration tests | Test pipeline với DB thật (Qdrant local) |
| Signal tests | Verify cross-thread signal payload không thay đổi |

### Nguyên tắc viết test

- Dùng `MockKnowledgeStore(IKnowledgeStore)` thay Qdrant thật trong unit test
- Test isolation: mỗi test không phụ thuộc test khác
- Mọi Worker test phải chạy trong QApplication context

---

## Pre-commit Checklist

```
[ ] python production_check.py → 0 Tier A FAIL
[ ] python run_tests.py        → tất cả PASS
[ ] Không có import mới vi phạm Dependency Direction
[ ] Signal payload không thay đổi (nếu có)
[ ] ADR được cập nhật cho quyết định kiến trúc mới
```
