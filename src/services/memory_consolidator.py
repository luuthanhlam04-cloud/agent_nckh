"""
memory_consolidator.py - Tri nho Ngam dinh ban dem (Giai doan 5 - Refactored)
==============================================================================
Thay doi so voi phien ban cu:
  - Xoa hoan toan vault_path / Profile.md dependency.
  - Nhan IMemoryStore qua Dependency Injection thay vi duong dan thu muc.
  - _write_profile() -> memory_store.save_daily_summary() (SQLite).
  - Giu nguyen: APScheduler, check_and_catchup(), _reduce_with_gemini().

Map-Reduce Pipeline:
  Map   : Doc toan bo ConversationMemory._window
  Reduce: Gemini Flash loc su kien rac (mo app, bat nhac) -> giu tri thuc
  Write : memory_store.save_daily_summary() -> SQLite daily_summaries

LUU Y QUAN TRONG:
  - Dung BackgroundScheduler (thread-based), KHONG dung AsyncIOScheduler
    vi AsyncIOScheduler yeu cau chay trong asyncio event loop hien tai,
    xung dot voi Qt Event Loop dang giu Main Thread.
  - last_consolidated_date duoc luu vao file .consolidation_state de
    ton tai qua cac lan khoi dong lai (restart-persistent).
"""

import os
import json
import logging
import gc
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.core.interfaces import IMemoryStore

logger = logging.getLogger("MemoryConsolidator")

# File luu trang thai ngay cuoi cung da consolidate
# Dat trong thu muc goc du an (ben canh main.py)
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    ".consolidation_state"
)

_REDUCE_SYSTEM_PROMPT = """
Bạn là bộ lọc trí nhớ thông minh của một AI trợ lý nghiên cứu khoa học.

Nhiệm vụ: Phân tích đoạn lịch sử hội thoại của ngày hôm nay và tạo bản tóm tắt ngắn gọn.

Quy tắc lọc:
- XÓA BỎ: các sự kiện thường nhật (mở app, bật nhạc, kiểm tra giờ, lệnh hệ điều hành, câu hỏi đơn giản)
- GIỮ LẠI: kiến thức khoa học được thảo luận, khái niệm quan trọng, vấn đề nghiên cứu, phát hiện mới
- CƯỜNG ĐỘ: giữ lại những chủ đề/từ khóa được nhắc đến nhiều lần (thể hiện sự quan tâm sâu)

Định dạng đầu ra (Markdown, tiếng Việt):
## Tri Thức Nổi Bật Trong Ngày
[Tóm tắt ngắn gọn những gì đã học]

## Các Chủ Đề Được Thảo Luận Nhiều
[Danh sách bullet các chủ đề chính]

## Ghi Chú Nghiên Cứu
[Bất kỳ phát hiện hoặc vấn đề còn đang cần theo dõi]

Nếu không có nội dung học thuật nào đáng ghi lại, chỉ viết: "Không có nội dung học thuật trong ngày."
""".strip()


class MemoryConsolidator:
    """
    Quan ly viec hoi tu va luu tru tri nho dai han hang dem.

    Dependency Injection (inject tu main.py):
      memory       : ConversationMemory instance (bo nho ngan han RAM)
      memory_store : IMemoryStore (SQLiteMemoryStore hoac bat ky impl nao)
      gemini_key   : GEMINI_API_KEY de goi Flash
    """

    def __init__(
        self,
        memory,                        # ConversationMemory instance
        memory_store: IMemoryStore,    # IMemoryStore (DIP)
        gemini_api_key: str = "",
    ):
        self._memory       = memory
        self._store        = memory_store
        self._api_key      = gemini_api_key
        self._scheduler    = None

        logger.info("[MemoryConsolidator] Khoi tao voi SQLiteMemoryStore.")

    # ── State Persistence ────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        """Doc trang thai cuoi cung tu file .consolidation_state."""
        try:
            if os.path.exists(_STATE_FILE):
                with open(_STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning("[MemoryConsolidator] Khong doc duoc state: %s", e, exc_info=True)
        return {"last_consolidated_date": None}

    def _save_state(self, consolidated_date: date):
        """Luu ngay consolidate moi nhat vao file .consolidation_state."""
        try:
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"last_consolidated_date": consolidated_date.isoformat()}, f)
        except Exception as e:
            logger.error("[MemoryConsolidator] Khong luu duoc state: %s", e, exc_info=True)

    # ── Catch-up Logic ───────────────────────────────────────────────────────

    def check_and_catchup(self):
        """
        [Risk 1 Fix] Kiem tra khi khoi dong: Neu may bi ngu dong va bo lo
        cronjob dem truoc -> tu dong chay bu.

        Goi ngay sau khi MemoryConsolidator duoc tao (trong main.py).
        """
        state    = self._load_state()
        last_str = state.get("last_consolidated_date")

        if last_str is None:
            logger.info("[MemoryConsolidator] Lan chay dau tien, khong can catch-up.")
            return

        try:
            last_date = date.fromisoformat(last_str)
        except ValueError:
            logger.warning("[MemoryConsolidator] State file bi hong, reset.")
            return

        today = date.today()
        if last_date < today:
            days_missed = (today - last_date).days
            logger.warning(
                "[MemoryConsolidator] Bo lo %d ngay consolidate. "
                "Dang chay bu...", days_missed
            )
            self.run_consolidation(is_catchup=True)
        else:
            logger.info(
                "[MemoryConsolidator] Trang thai hien tai: da consolidate ngay %s.", last_str
            )

    # ── Core Pipeline ────────────────────────────────────────────────────────

    def run_consolidation(self, is_catchup: bool = False):
        """
        Thuc hien Map-Reduce:
          Doc lich su hoi thoai -> Gemini Flash -> SQLiteMemoryStore.

        Dat safe: neu khong co API key hoac memory trong -> ghi note thong bao.
        """
        tag = "[CATCH-UP] " if is_catchup else ""
        logger.info("[MemoryConsolidator] %sBat dau hoi tu tri nho...", tag)

        # ── Map: doc conversation window ─────────────────────────────────────
        if not self._memory or len(self._memory) == 0:
            logger.info("[MemoryConsolidator] Khong co hoi thoai de hoi tu.")
            self._store.save_daily_summary(
                date.today().isoformat(),
                "Khong co noi dung hoc thuat trong ngay."
            )
            self._save_state(date.today())
            return

        raw_log = self._memory.get_context_string()
        logger.info("[MemoryConsolidator] Da map %d cau thoai.", len(self._memory))

        # ── Reduce: goi Gemini Flash loc va tom tat ──────────────────────────
        summary = self._reduce_with_gemini(raw_log)

        # ── Write: luu vao SQLite thay vi Profile.md ─────────────────────────
        self._store.save_daily_summary(date.today().isoformat(), summary)

        gc.collect()
        self._save_state(date.today())
        logger.info("[MemoryConsolidator] %sHoan thanh. Da ghi vao SQLite.", tag)

    def _reduce_with_gemini(self, raw_log: str) -> str:
        """
        Goi Gemini Flash de loc va tom tat chat log.
        Fallback ve raw log neu API loi.
        """
        if not self._api_key:
            logger.warning("[MemoryConsolidator] Khong co GEMINI_API_KEY. Fallback: luu raw log.")
            return f"[Raw log - chua duoc hoi tu vi thieu API key]\n\n{raw_log}"

        try:
            import google.genai as genai
            import google.genai.types as genai_types

            client      = genai.Client(api_key=self._api_key)
            user_prompt = (
                f"Duoi day la lich su hoi thoai can loc va tom tat:\n\n"
                f"{raw_log}\n\n"
                f"Hay tao ban tom tat theo cau truc da duoc chi dinh."
            )

            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_REDUCE_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=1024,
                ),
            )
            summary = response.text.strip()
            logger.info("[MemoryConsolidator] Gemini Flash da hoi tu %d ky tu.", len(summary))
            return summary

        except Exception as e:
            logger.error(
                "[MemoryConsolidator] Loi Gemini Flash: %s. Fallback raw log.", e, exc_info=True
            )
            return f"[Hoi tu that bai: {str(e)[:100]}]\n\n{raw_log}"

    # ── Scheduler Lifecycle ──────────────────────────────────────────────────

    def start_scheduler(self):
        """
        Khoi dong APScheduler BackgroundScheduler.
        Cronjob 0:00 hang dem - thread rieng, khong block Qt.

        QUAN TRONG: Dung BackgroundScheduler (thread-based), KHONG dung
        AsyncIOScheduler de tranh conflict voi Qt Event Loop tren Main Thread.
        """
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger

            self._scheduler = BackgroundScheduler(
                job_defaults={"misfire_grace_time": 3600},
                timezone="Asia/Ho_Chi_Minh",
            )

            self._scheduler.add_job(
                func=self.run_consolidation,
                trigger=CronTrigger(hour=0, minute=0),
                id="nightly_memory_consolidation",
                name="Hoi Tu Tri Nho Ban Dem",
                replace_existing=True,
            )

            self._scheduler.start()
            logger.info(
                "[MemoryConsolidator] APScheduler da khoi dong. "
                "Cronjob se chay luc 0:00 hang dem (Asia/Ho_Chi_Minh)."
            )

        except ImportError:
            logger.warning(
                "[MemoryConsolidator] apscheduler chua cai. "
                "Cronjob bi tat. Chay: pip install apscheduler"
            )
        except Exception as e:
            logger.error("[MemoryConsolidator] Loi khoi dong scheduler: %s", e, exc_info=True)

    def stop_scheduler(self):
        """Dung scheduler khi app thoat."""
        if self._scheduler and self._scheduler.running:
            try:
                self._scheduler.shutdown(wait=False)
                logger.info("[MemoryConsolidator] Scheduler da dung.")
            except Exception as e:
                logger.error("[MemoryConsolidator] Loi dung scheduler: %s", e, exc_info=True)
