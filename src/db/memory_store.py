"""
memory_store.py - SQLite Memory Persistence Layer
==================================================
Implements IMemoryStore interface cho Digital Scholar.

Schema (3 bảng):
  daily_summaries : Bản tóm tắt ngày do APScheduler/Gemini tạo ra.
                    Primary key = date (YYYY-MM-DD), INSERT OR REPLACE.
  quick_notes     : Ghi chú nhanh do user ra lệnh "Nhớ cái này", v.v.
                    Append-only, có timestamp.
  memories        : Memory entries tổng quát (fact, concept, preference...).
                    Có trường embedding TEXT dự phòng cho semantic memory.

DB Path:
  Windows: C:\\Users\\<user>\\AppData\\Local\\DigitalScholar\\memory.db
  Fallback: <project_root>/memory.db

Thiết kế:
  - Thread-safe: dùng threading.Lock cho mọi write operation.
  - Lazy-init: kết nối chỉ được tạo khi cần (tiết kiệm RAM khi test).
  - check_same_thread=False: cho phép dùng từ nhiều thread (Qt + APScheduler).
  - Tương thích Clean Architecture: không import gì từ src.core hay src.ui.
"""

import gc
import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.core.interfaces import IMemoryStore

logger = logging.getLogger("SQLiteMemoryStore")

# ── Schema SQL ────────────────────────────────────────────────────────────────

_DDL_DAILY_SUMMARIES = """
CREATE TABLE IF NOT EXISTS daily_summaries (
    date       TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_DDL_QUICK_NOTES = """
CREATE TABLE IF NOT EXISTS quick_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
"""

_DDL_MEMORIES = """
CREATE TABLE IF NOT EXISTS memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT    NOT NULL DEFAULT 'fact',
    content    TEXT    NOT NULL,
    embedding  TEXT,
    created_at TEXT    NOT NULL
);
"""

_DDL_RETRIEVAL_LOG = """
CREATE TABLE IF NOT EXISTS retrieval_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query           TEXT    NOT NULL,
    embedding_model TEXT,
    reranker        TEXT,
    policy          TEXT,
    collection      TEXT,
    chunks_json     TEXT,
    latency_ms      REAL,
    created_at      TEXT    NOT NULL
);
"""

# ── Helper: xác định đường dẫn DB ────────────────────────────────────────────

def _get_default_db_path() -> Path:
    """
    Trả về đường dẫn mặc định của memory.db.
    Ưu tiên AppData/Local/DigitalScholar/ trên Windows.
    Fallback về <project_root>/memory.db.
    """
    if os.name == "nt":  # Windows
        appdata = os.environ.get("LOCALAPPDATA", "")
        if appdata:
            app_dir = Path(appdata) / "DigitalScholar"
            app_dir.mkdir(parents=True, exist_ok=True)
            return app_dir / "memory.db"

    # Fallback: thư mục gốc dự án (ngang hàng với main.py)
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "memory.db"


# ══════════════════════════════════════════════════════════════════════════════
#  SQLiteMemoryStore
# ══════════════════════════════════════════════════════════════════════════════

class SQLiteMemoryStore(IMemoryStore):
    """
    Concrete implementation của IMemoryStore dùng SQLite.

    Ví dụ sử dụng:
        store = SQLiteMemoryStore()
        store.save_quick_note("Nhớ: RAG là Retrieval-Augmented Generation")
        notes = store.get_recent_notes(5)
        store.close()
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = Path(db_path) if db_path else _get_default_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._connect()

    # ── Private ──────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        """Kết nối SQLite và tạo schema nếu chưa có."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,  # cho phép nhiều thread dùng chung
            )
            self._conn.row_factory = sqlite3.Row  # trả về dict-like rows
            self._conn.execute("PRAGMA journal_mode=WAL;")  # cải thiện concurrent write
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._create_schema()
            logger.info("[MemoryStore] Đã kết nối SQLite: %s", self._db_path)
        except Exception as e:
            logger.error("[MemoryStore] Lỗi kết nối SQLite: %s", e, exc_info=True)
            raise

    def _create_schema(self) -> None:
        """Tạo các bảng nếu chưa tồn tại."""
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                _DDL_DAILY_SUMMARIES + _DDL_QUICK_NOTES + _DDL_MEMORIES + _DDL_RETRIEVAL_LOG
            )
            self._conn.commit()
        logger.debug("[MemoryStore] Schema đã sẵn sàng.")

    def _now_iso(self) -> str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # ── IMemoryStore Implementation ───────────────────────────────────────────

    def save_daily_summary(self, date_str: str, content: str) -> None:
        """INSERT OR REPLACE bản tóm tắt ngày."""
        sql = """
            INSERT OR REPLACE INTO daily_summaries (date, content, updated_at)
            VALUES (?, ?, ?)
        """
        with self._lock:
            self._conn.execute(sql, (date_str, content, self._now_iso()))
            self._conn.commit()
        logger.info("[MemoryStore] Đã lưu daily summary cho ngày %s.", date_str)

    def save_quick_note(self, content: str) -> None:
        """Append ghi chú nhanh."""
        sql = "INSERT INTO quick_notes (content, created_at) VALUES (?, ?)"
        with self._lock:
            self._conn.execute(sql, (content, self._now_iso()))
            self._conn.commit()
        logger.info("[MemoryStore] Ghi chú nhanh đã lưu: %s...", content[:60])

    def save_memory(self, memory_type: str, content: str) -> None:
        """Lưu memory entry tổng quát (embedding = None cho đến khi implement)."""
        sql = """
            INSERT INTO memories (type, content, embedding, created_at)
            VALUES (?, ?, NULL, ?)
        """
        with self._lock:
            self._conn.execute(sql, (memory_type, content, self._now_iso()))
            self._conn.commit()
        logger.info("[MemoryStore] Memory[%s] đã lưu.", memory_type)

    def get_recent_summaries(self, n: int = 7) -> List[Dict[str, Any]]:
        """Lấy n bản tóm tắt gần nhất, sắp xếp mới → cũ."""
        sql = """
            SELECT date, content, updated_at
            FROM daily_summaries
            ORDER BY date DESC
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(sql, (n,)).fetchall()
        return [dict(row) for row in rows]

    def get_recent_notes(self, n: int = 20) -> List[Dict[str, Any]]:
        """Lấy n ghi chú gần nhất, mới → cũ."""
        sql = """
            SELECT id, content, created_at
            FROM quick_notes
            ORDER BY id DESC
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(sql, (n,)).fetchall()
        return [dict(row) for row in rows]

    def get_memories_by_type(
        self, memory_type: str, n: int = 20
    ) -> List[Dict[str, Any]]:
        """Lấy memories theo type (không bắt buộc trong interface, bonus method)."""
        sql = """
            SELECT id, type, content, created_at
            FROM memories
            WHERE type = ?
            ORDER BY id DESC
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(sql, (memory_type, n)).fetchall()
        return [dict(row) for row in rows]

    def log_retrieval(self, query: str, config_meta: Dict[str, Any], chunks: List[Dict[str, Any]], latency_ms: float) -> None:
        import json
        sql = """
            INSERT INTO retrieval_log (
                query, embedding_model, reranker, policy, collection, chunks_json, latency_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Chuyển đổi chunks thành JSON để lưu
        # Giữ lại các trường quan trọng để tiết kiệm dung lượng, nhưng đủ để debug
        clean_chunks = []
        for c in chunks:
            clean_chunk = {
                "chunk_id": c.get("chunk_id"),
                "score": c.get("score"),
                "rerank_score": c.get("rerank_score"),
                "source": c.get("source"),
                "rank_before": c.get("rank_before"),
                "rank_after": c.get("rank_after"),
                "text_preview": c.get("text", "")[:100] + "..." if c.get("text") else ""
            }
            clean_chunks.append(clean_chunk)
            
        chunks_json = json.dumps(clean_chunks, ensure_ascii=False)
        config_json = json.dumps(config_meta, ensure_ascii=False)
        
        with self._lock:
            self._conn.execute(sql, (
                query,
                config_meta.get("embedding_model", ""),
                config_meta.get("reranker", ""),
                config_meta.get("policy", ""),
                config_json, # Sử dụng cột collection để lưu toàn bộ config_json
                chunks_json,
                latency_ms,
                self._now_iso()
            ))
            self._conn.commit()
        logger.debug(f"[MemoryStore] Đã lưu retrieval log cho query: '{query[:30]}...'")

    def close(self) -> None:
        """Đóng kết nối SQLite an toàn."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                    self._conn = None
                    logger.info("[MemoryStore] Đã đóng kết nối SQLite.")
                except Exception as e:
                    logger.error("[MemoryStore] Lỗi đóng kết nối: %s", e)
        gc.collect()
