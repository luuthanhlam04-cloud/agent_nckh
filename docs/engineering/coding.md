# Coding Standards

> Phân loại theo 3 tier: **A** (FAIL), **B** (FAIL/WARN), **C** (WARN/INFO).

---

## Tier A — Architecture Safety (vi phạm = CI FAIL)

Xem [threading.md](threading.md) và [architecture.md](architecture.md) cho các rule threading và dependency.

---

## Tier B — Code Quality

### B1. No Bare Except — FAIL

```python
# Sai:
except:
    pass

except Exception:
    pass  # Không có logging

# Đúng:
except ValueError as e:
    logger.error("[ModuleName] Mô tả: %s", e, exc_info=True)
```

### B2. No Magic Numbers — WARN

```python
# Sai:
time.sleep(4)
top_k = 5
threshold = 0.87

# Đúng (đầu file):
PPTX_SLEEP_SECONDS = 4
RAG_TOP_K_DEFAULT = 5
INTENT_SCORE_THRESHOLD = 0.87
```

### B3. Function Length — WARN (>80 dòng)

Hàm dài hơn 80 dòng nên được tách thành các hàm nhỏ hơn.  
Exception: `__init__` với nhiều setup logic có thể dài hơn nếu có lý do.

### B4. Class Length — WARN (>500 dòng)

Class dài hơn 500 dòng thường là God Object. Xem xét tách responsibility.

### B5. File Length — WARN (>1000 dòng)

File dài hơn 1000 dòng nên được tách module.  
*Ví dụ hiện tại cần fix: `spotlight.py` (1325 dòng).*

### B6. Config Rule — WARN

`os.getenv()` chỉ được gọi trong `src/shared/config.py`.  
Các module khác import từ `src.shared.config`.

### B7. Logging Rule — WARN

```python
# Bắt buộc — mỗi module có logger riêng:
logger = logging.getLogger(__name__)

# Nghiêm cấm — ghi đè config toàn app:
logging.basicConfig(level=logging.DEBUG)
```

### B8. TODO/FIXME Tracking — WARN

`TODO`, `FIXME`, `HACK` trong source code phải được track qua issue tracker.  
Trong code chỉ được giữ tối đa 7 ngày.

---

## Tier C — Convention (vi phạm = WARN/INFO, có thể có ngoại lệ)

### C1. Naming

| Loại | Convention | Lý do | Ngoại lệ |
|------|-----------|-------|----------|
| QThread class | Hậu tố `*Worker` | Nhìn tên biết cross-thread risk | Document lý do trong docstring |
| pyqtSignal | Tiền tố `sig_*` | Data đang cross-thread | — |
| Slot handler | Tiền tố `_on_*` | Được trigger từ thread khác | `handle_*()` nếu có lý do |
| Private attribute | Tiền tố `_` | Ngăn accidental public API | — |
| State flag | `_is_*` / `_has_*` | Phân biệt với data attribute | — |

### C2. Import Order (PEP 8)

```python
# 1. Standard Library
import os
import threading

# 2. Third-party
from PyQt6.QtCore import QThread
import numpy as np

# 3. Internal modules
from src.core.interfaces import IKnowledgeStore
```

### C3. Type Hints

Tất cả public function (không bắt đầu bằng `_`) phải có type annotation:

```python
# Đúng:
def search(self, query: str, top_k: int) -> list[dict]:

# Sai:
def search(self, query, top_k):
```

### C4. Import trong function — WARN

Import bên trong hàm nên tránh. Nếu bắt buộc (circular dependency), phải có comment giải thích:

```python
def _init_parser(self):
    # Lazy import: tránh circular dependency với watchdog_listener
    from src.utils.parser import PDFParser
    return PDFParser()
```

---

## Anti-Regression Protocol

Trước khi sửa bất kỳ logic nào ở luồng A, **bắt buộc** trace Signal:

1. Xác định Signal nào luồng A emit
2. Xác định Slot nào đang nhận Signal đó
3. Nếu đổi payload của Signal → cập nhật **tất cả** receiver trước khi merge

Không tự ý đổi cấu trúc tham số Signal nếu chưa cập nhật receiver.
