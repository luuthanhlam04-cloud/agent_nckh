"""
watchdog_listener.py - Tiến trình Giám sát Hộp thư Tài liệu (Inbox Watcher)
=============================================================================
Chức năng:
  - Giám sát liên tục thư mục 01_Inbox/ của Obsidian Vault bằng watchdog.
  - Khi phát hiện file PDF/PPTX mới được thả vào, tự động kích hoạt luồng:
      1. Parser bóc tách tài liệu -> chunks
      2. HybridRAG nạp chunks vào Qdrant Local + Neo4j Cloud
      3. Di chuyển file gốc sang 02_Knowledge/ để tránh xử lý lại
  - Chạy ngầm bằng asyncio trong Worker Thread riêng (không block UI thread).
  - Hàng đợi asyncio.Queue đảm bảo không xử lý đồng thời quá nhiều file cùng lúc
    (bảo vệ RAM và tránh bùng Rate Limit API).

Thiết kế:
  - InboxEventHandler : Bắt sự kiện file system và đẩy đường dẫn vào Queue.
  - InboxWatcher      : Khởi chạy watchdog Observer + asyncio event loop ngầm.
  - start_watcher()   : Hàm tiện lợi để khởi chạy từ main.py.
"""

import os
import asyncio
import logging
import shutil
import threading
from pathlib import Path
from typing import Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

# ─── Logging ─────────────────────────────────────────────────────────────────
# [S3-FIX] Không gọi basicConfig ở đây — main.py đã cấu hình toàn cục với
# FileHandler + StreamHandler. Gọi lại chỉ tạo duplicate handler.
logger = logging.getLogger("WatchdogListener")

# ─── Định dạng file được chấp nhận ────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".ppt"}



# ══════════════════════════════════════════════════════════════════════════════
#  InboxEventHandler - Bắt sự kiện file mới
# ══════════════════════════════════════════════════════════════════════════════
import time

class InboxEventHandler(FileSystemEventHandler):
    """
    Lắng nghe sự kiện 'file mới được tạo' hoặc 'chỉnh sửa' trong thư mục 01_Inbox/.
    Có tích hợp cơ chế Debounce (Đệm thời gian 2s) để tránh Windows bắn quá nhiều
    sự kiện on_modified liên tiếp gây gọi API trùng lặp.
    """

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        """
        Args:
            queue: Hàng đợi bất đồng bộ nhận đường dẫn file mới.
            loop : Event loop của Worker Thread (để thread-safe queue.put).
        """
        super().__init__()
        self._queue = queue
        self._loop = loop
        self._debounce_dict = {}

    def on_created(self, event):
        self._handle_event(event)

    def on_modified(self, event):
        self._handle_event(event)

    def _handle_event(self, event):
        """Xử lý chung cho created và modified với Debounce."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        ext = file_path.suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            return

        # Bỏ qua file ẩn (file tạm của hệ điều hành, .DS_Store, ~$temp.pptx...)
        if file_path.name.startswith(".") or file_path.name.startswith("~$"):
            return

        current_time = time.time()
        path_str = str(file_path)
        last_time = self._debounce_dict.get(path_str, 0)

        # DEBOUNCE: Nếu chưa quá 2 giây kể từ sự kiện cuối, bỏ qua
        if current_time - last_time < 2.0:
            return

        self._debounce_dict[path_str] = current_time
        # [B4-FIX] Don dep debounce_dict khi qua 100 entries de tranh memory leak
        # khi nhieu file duoc drop vao inbox qua nhieu ngay. Xoa cac entry cu nhat.
        if len(self._debounce_dict) > 100:
            oldest_keys = sorted(self._debounce_dict, key=lambda k: self._debounce_dict[k])[:50]
            for k in oldest_keys:
                del self._debounce_dict[k]
        logger.info(f"[Watchdog] 📥 Phát hiện tài liệu mới (Debounced): {file_path.name}")

        # Thread-safe: đưa đường dẫn vào asyncio Queue từ OS thread
        asyncio.run_coroutine_threadsafe(
            self._queue.put(path_str),
            self._loop
        )


# ══════════════════════════════════════════════════════════════════════════════
#  InboxWatcher - Điều phối toàn bộ luồng giám sát & xử lý ngầm
# ══════════════════════════════════════════════════════════════════════════════
class InboxWatcher:
    """
    Kết hợp watchdog Observer + asyncio Worker để giám sát và xử lý tài liệu:

    Kiến trúc luồng:
    ┌────────────────────────────────────────────────────────────────┐
    │  OS Thread (watchdog Observer)                                  │
    │    └── InboxEventHandler.on_created() -> Queue.put(path)        │
    │                                                                  │
    │  Worker Thread (asyncio event loop)                              │
    │    └── _process_queue() -> parse -> ingest -> move file          │
    └────────────────────────────────────────────────────────────────┘

    Tách biệt 2 luồng đảm bảo UI Thread KHÔNG bao giờ bị chặn khi
    đang bóc tách file PDF học thuật hàng trăm trang.
    """

    def __init__(
        self,
        inbox_path: str,
        knowledge_path: str,
        hybrid_rag=None,
    ):
        """
        Args:
            inbox_path    : Đường dẫn đến Obsidian_Vault/01_Inbox/.
            knowledge_path: Đường dẫn đến Obsidian_Vault/02_Knowledge/ (thư mục đích).
            hybrid_rag    : Instance HybridRAG đã khởi tạo (optional, có thể inject sau).
        """
        self.inbox_path = inbox_path
        self.knowledge_path = knowledge_path
        self._hybrid_rag = hybrid_rag

        # Tạo thư mục nếu chưa tồn tại
        os.makedirs(inbox_path, exist_ok=True)
        os.makedirs(knowledge_path, exist_ok=True)

        # [C2-FIX] Queue KHÔNG tạo ở đây (main thread) mà sẽ được tạo bên trong
        # _run_async_loop() SAU KHI asyncio.set_event_loop() được gọi.
        # Tạo Queue ở main thread trước khi loop chạy là race condition.
        self._queue: Optional[asyncio.Queue] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._observer: Optional[Observer] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._loop_ready = threading.Event()   # [C2-FIX] Signal khi loop đã sẵn sàng

    def set_hybrid_rag(self, hybrid_rag):
        """Inject HybridRAG instance sau khi khởi tạo (dependency injection)."""
        self._hybrid_rag = hybrid_rag

    def start(self):
        """
        Khởi động toàn bộ hệ thống giám sát ngầm:
        1. Tạo asyncio event loop mới trên Worker Thread.
        2. Worker Thread khởi tạo Queue RỒI mới signal sẵn sàng.
        3. Khởi động watchdog Observer SAU KHI loop đã chạy.

        [C2-FIX] Observer chỉ start sau khi _loop_ready.wait() trả về True,
        đảm bảo không có sự kiện file nào đến trước khi Queue được tạo.
        """
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._loop_ready.clear()

        # Khởi động Worker Thread — Queue sẽ được tạo bên trong thread này
        self._worker_thread = threading.Thread(
            target=self._run_async_loop,
            name="InboxWorker",
            daemon=True,
        )
        self._worker_thread.start()

        # [C2-FIX] Chờ worker thread báo hiệu Queue đã sẵn sàng (tối đa 5 giây)
        if not self._loop_ready.wait(timeout=5.0):
            logger.error("[Watchdog] Worker loop không khởi động được trong 5s!")
            return

        # Chỉ bắt đầu lắng nghe file SAU KHI Queue đã tồn tại
        event_handler = InboxEventHandler(queue=self._queue, loop=self._loop)
        self._observer = Observer()
        self._observer.schedule(event_handler, path=self.inbox_path, recursive=False)
        self._observer.start()

        logger.info("[Watchdog] 👁️  Đang giám sát thư mục: %s", self.inbox_path)
        logger.info("[Watchdog] Hệ thống sẵn sàng nhận tài liệu mới.")

    def stop(self):
        """Dừng toàn bộ hệ thống giám sát và dọn sạch tài nguyên."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("[Watchdog] Observer đã dừng.")
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("[Watchdog] Đã dừng hệ thống giám sát.")

    def _run_async_loop(self):
        """
        Chạy asyncio event loop trên Worker Thread.
        [C2-FIX] Tạo Queue TẠI ĐÂY sau khi set_event_loop() — đảm bảo
        Queue được gắn đúng vào event loop đang chạy trong thread này.
        """
        asyncio.set_event_loop(self._loop)
        # Tạo Queue trong ngữ cảnh event loop đã được set
        self._queue = asyncio.Queue()
        # Báo hiệu cho start() biết Queue đã sẵn sàng
        self._loop_ready.set()
        self._loop.run_until_complete(self._process_queue())

    async def _process_queue(self):
        """
        Coroutine chay vinh vien, lay file path tu Queue va xu ly tuan tu.
        Xu ly tuan tu (khong concurrent) de tranh bung phat Rate Limit API.
        """
        logger.info("[Watchdog] Worker Queue dang lang nghe...")
        while self._running:
            try:
                # Cho file moi trong Queue (timeout 1s de co the kiem tra _running)
                file_path = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._handle_new_file(file_path)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue  # Timeout binh thuong, tiep tuc vong lap
            except asyncio.CancelledError:
                # [BUG-10 FIX] CancelledError phai duoc re-raise de asyncio co the
                # dung sach event loop khi loop.stop() duoc goi tu stop().
                logger.info("[Watchdog] Queue worker da bi huy, dung sach.")
                break
            except Exception as e:
                logger.error("[Watchdog] Loi trong process_queue: %s", e)

    async def _handle_new_file(self, file_path: str):
        """
        Xử lý một file tài liệu mới:
        1. Bóc tách (parse) -> chunks
        2. Nạp vào HybridRAG (Qdrant + Neo4j)
        3. Lưu Markdown vào 02_Knowledge/
        4. Di chuyển file gốc sang 02_Knowledge/ để đánh dấu đã xử lý

        Args:
            file_path: Đường dẫn tuyệt đối đến file mới trong 01_Inbox/.
        """
        path = Path(file_path)
        logger.info("[Watchdog] Bat dau xu ly: %s", path.name)

        try:
            # [I1 FIX] Windows race condition: on_created() kich hoat khi file bat dau ghi,
            # nhung file co the chua ghi xong. Poll size de biet khi nao file on dinh.
            prev_size = -1
            for attempt in range(12):   # Toi da 6 giay (12 x 0.5s)
                await asyncio.sleep(0.5)
                if not path.exists():
                    continue
                curr_size = path.stat().st_size
                if curr_size > 0 and curr_size == prev_size:
                    break   # Size on dinh -> file da ghi xong
                prev_size = curr_size
            else:
                logger.warning("[Watchdog] File '%s' khong on dinh sau 6s. Bo qua.", path.name)
                return

            # Bước 1: Import parser (tránh circular import)
            from src.utils.parser import parse_document, PDFParser, PPTXParser

            # Bóc tách tài liệu thành chunks (chạy trong executor để không block event loop)
            # [BUG-3 FIX] Dùng get_running_loop() thay vì get_event_loop() (deprecated Python 3.10+,
            # raise RuntimeError trong 3.12+ nếu không có loop đang chạy trong context hiện tại).
            loop = asyncio.get_running_loop()
            chunks = await loop.run_in_executor(None, parse_document, file_path)

            if not chunks:
                logger.warning("[Watchdog] Khong boc tach duoc chunk nao tu: %s", path.name)
                return

            logger.info("[Watchdog] Boc tach duoc %d chunks tu %s", len(chunks), path.name)

            # Bước 2: Lưu Markdown sang 02_Knowledge/
            # [BUG-3 FIX] Tiếp tục dùng get_running_loop() cho nhất quán
            loop = asyncio.get_running_loop()
            md_output_path = await loop.run_in_executor(
                None,
                self._save_markdown,
                file_path,
                chunks,
            )

            # Bước 3: Nạp vào HybridRAG nếu đã được inject
            if self._hybrid_rag:
                # entities và relationships sẽ được trích xuất bởi LLM trong Giai đoạn 3
                # Hiện tại nạp chunks thuần để database hoạt động trước
                await loop.run_in_executor(
                    None,
                    self._hybrid_rag.qdrant.upsert_chunks,
                    chunks,
                )
                logger.info(f"[Watchdog] ✅ Đã nạp {len(chunks)} chunks vào Qdrant.")
            else:
                logger.warning(
                    "[Watchdog] HybridRAG chưa được inject. "
                    "Chunks chỉ được lưu vào Markdown, chưa vào Qdrant."
                )

            # Bước 4: Di chuyển file gốc sang 02_Knowledge/ (đánh dấu đã xử lý)
            # [FIX] Xử lý FileExistsError khi cùng file được drop 2 lần:
            # thêm timestamp vào tên để không ghi đè file cũ
            dest_path = os.path.join(self.knowledge_path, path.name)
            if os.path.exists(dest_path):
                from datetime import datetime as _dt
                stem, ext = os.path.splitext(path.name)
                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                dest_path = os.path.join(self.knowledge_path, f"{stem}_{ts}{ext}")
                logger.warning("[Watchdog] File trùng tên, đổi thành: %s", os.path.basename(dest_path))
            shutil.move(file_path, dest_path)
            logger.info(f"[Watchdog] 📦 Đã lưu file gốc vào: {dest_path}")


        except Exception as e:
            logger.error(f"[Watchdog] ❌ Lỗi xử lý file '{path.name}': {e}", exc_info=True)

    def _save_markdown(self, file_path: str, chunks: list) -> str:
        """Lưu kết quả bóc tách thành file Markdown trong 02_Knowledge/."""
        stem = Path(file_path).stem
        md_path = os.path.join(self.knowledge_path, f"{stem}.md")
        ext = Path(file_path).suffix.lower()

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {stem}\n")
            f.write(f"<!-- Source: {Path(file_path).name} -->\n\n")
            for chunk in chunks:
                label = "Page" if ext == ".pdf" else "Slide"
                f.write(f"<!-- {label} {chunk['page']} -->\n")
                f.write(chunk["text"] + "\n\n---\n\n")

        logger.info(f"[Watchdog] 📝 Đã lưu Markdown: {md_path}")
        return md_path


# ─── Hàm tiện lợi khởi động từ main.py ───────────────────────────────────────
def start_watcher(
    vault_path: str,
    hybrid_rag=None,
) -> InboxWatcher:
    """
    Khởi động InboxWatcher và trả về instance để main.py có thể stop() khi cần.

    Args:
        vault_path : Đường dẫn gốc của Obsidian Vault.
        hybrid_rag : Instance HybridRAG (optional, inject sau khi DB sẵn sàng).

    Returns:
        InboxWatcher đang chạy ngầm.
    """
    inbox_path = os.path.join(vault_path, "01_Inbox")
    knowledge_path = os.path.join(vault_path, "02_Knowledge")

    watcher = InboxWatcher(
        inbox_path=inbox_path,
        knowledge_path=knowledge_path,
        hybrid_rag=hybrid_rag,
    )
    watcher.start()
    return watcher


# ─── Test nhanh khi chạy trực tiếp ───────────────────────────────────────────
if __name__ == "__main__":
    import time

    # Dùng thư mục trong dự án để test (không cần Obsidian thật)
    TEST_VAULT = os.path.join(os.path.dirname(__file__), "../../Obsidian_Vault")

    print(f"[TEST] Khởi động WatchdogListener trên: {TEST_VAULT}/01_Inbox")
    print("[TEST] Hãy thử thả một file PDF vào thư mục 01_Inbox/ và xem log!")
    print("[TEST] Nhấn Ctrl+C để dừng.\n")

    watcher = start_watcher(vault_path=TEST_VAULT)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[TEST] Đang dừng watchdog...")
        watcher.stop()
        print("[TEST] Đã dừng.")
