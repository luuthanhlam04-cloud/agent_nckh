# Threading Model

> **Mức độ:** Tier A — vi phạm bất kỳ rule nào dưới đây = CI FAIL ngay lập tức.  
> **Nền tảng:** PyQt6 QThread + asyncio trong Worker Thread riêng biệt.

---

## 1. Bất biến Main Thread (Qt Event Loop)

**Tuyệt đối nghiêm cấm** trên Main Thread:
- Gọi bất kỳ blocking I/O (file, network, subprocess)
- Gọi API bất đồng bộ (Gemini, OpenRouter, Edge-TTS)
- Phân tích âm thanh (STT/TTS)
- `time.sleep()` — dù chỉ 1ms

**Hậu quả:** Qt Event Loop đứng → Windows báo "Not Responding" → trải nghiệm người dùng hỏng hoàn toàn.

---

## 2. Worker Isolation

Một tính năng mới = Một Worker riêng biệt.

Workers **không được**:
- Chia sẻ vùng nhớ với nhau
- Sửa trực tiếp biến của Worker khác
- Import QWidget, QMainWindow, QApplication

Workers **chỉ được** giao tiếp qua `pyqtSignal`.

---

## 3. Vòng đời Worker (Anti-RuntimeError)

PyQt6 object có 2 vòng đời: C++ object và Python wrapper.  
`deleteLater()` xóa C++ object nhưng Python ref vẫn tồn tại → crash khi gọi method.

**Pattern bắt buộc khi dọn dẹp Worker:**

```python
# 1. Gỡ Python ref TRƯỚC khi kết nối deleteLater
worker.finished.connect(lambda: setattr(self, '_worker', None))
worker.finished.connect(worker.deleteLater)

# 2. Mọi nơi gọi .isRunning() phải bọc try/except
try:
    if self._worker.isRunning():
        self._worker.terminate()
        self._worker.wait(3000)
except RuntimeError:
    self._worker = None  # C++ object đã bị xóa
```

---

## 4. asyncio trong Worker Thread

Bất kỳ Worker nào dùng `async/await` phải tự khởi tạo Event Loop nội bộ:

```python
def run(self):
    loop = asyncio.new_event_loop()   # Bắt buộc new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(self._async_task())
    finally:
        loop.close()
```

**Tuyệt đối không** dùng `asyncio.get_event_loop()` trong Worker Thread.

---

## 5. Thread-safe Singleton

Tài nguyên nặng nạp đúng 1 lần bằng `threading.Lock()`:

```python
_lock = threading.Lock()
_instance = None

def get_instance():
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:   # Double-checked locking
                _instance = HeavyResource()
    return _instance
```

Bắt buộc gọi `gc.collect()` sau STT transcription để giải phóng audio buffer.

---

## 6. Graceful Shutdown

Khi dừng Worker hoặc thoát app:

```python
# Thứ tự bắt buộc:
worker.stop()          # 1. Signal dừng
worker.wait(3000)      # 2. Chờ tối đa 3 giây
if worker.isRunning(): # 3. Force kill nếu vẫn kẹt
    worker.terminate()
```

Không bao giờ chỉ gọi `.stop()` rồi bỏ mặc → zombie thread.

---

## 7. Logging trong Multi-thread

**Nghiêm cấm** `print()` trong Worker (bị đè chữ hoặc mất trên terminal đa luồng).

Bắt buộc dùng `logging`:
```python
logger = logging.getLogger(__name__)   # Không tự gọi basicConfig()

# Trong except block:
except SomeError as e:
    logger.error("[WorkerName] Mô tả lỗi: %s", e, exc_info=True)
```

---

## 8. Signal Streaming (Generator Law)

Mọi luồng text AI phải dùng `yield` (Generator). Tuyệt đối không dùng `return <string>` trong Generator function — message lỗi sẽ không bao giờ đến caller.

```python
# Đúng:
def run_ai(query: str) -> Generator[str, None, None]:
    for chunk in llm.stream(query):
        yield chunk

# Sai:
def run_ai(query: str) -> Generator[str, None, None]:
    if error:
        return "Lỗi: ..."   # Message này KHÔNG bao giờ đến UI
```
