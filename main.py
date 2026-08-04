"""
main.py - Diem Khoi chay Background Daemon (Entry Point)
=========================================================
Luong khoi dong (Giai doan 4 - Da tich hop PyQt6 Spotlight UI):
  1. Load cau hinh tu .env
  2. Khoi tao HybridRAG (Qdrant Local + Neo4j Cloud) - lazy init
  3. Khoi dong InboxWatcher chay ngam giam sat 01_Inbox/
  4. Khoi chay Spotlight UI (PyQt6) + System Tray + Global Hotkey
  5. app.exec() giu tien trinh song (thay the while True)

Yeu cau he thong:
  - Chay voi quyen Administrator de bat phim tat toan cuc (keyboard library).
  - File .env phai duoc dien day du truoc khi chay (xem README.md).
  - PyQt6 phai duoc cai: pip install PyQt6
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()  # Phải nạp .env TRƯỚC khi import các module khác

from src.shared.settings import validate
validate()
import time
import signal
import logging
import gc
import functools
from pathlib import Path

# Fix loi Unicode khi in tieng Viet ra terminal (Windows)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception as e:
        _ = e  # Bỏ qua im lặng, gán biến giả để linter không flag pass

# --- Cau hinh Logging toan cuc ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("Main")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)  # Suppress missing property warnings
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# --- Duong dan Obsidian Vault ---
from src.shared.config import OBSIDIAN_VAULT_PATH
VAULT_PATH = OBSIDIAN_VAULT_PATH or r"C:\Users\luuth\Documents\NCKH\Data"


# ==============================================================================
#  Khoi tao cac thanh phan he thong (Giu nguyen tu Giai doan 1-3)
# ==============================================================================

def init_database():
    """
    Khoi tao ket noi HybridRAG (Qdrant + Neo4j).
    Tra ve instance HybridRAG hoac None neu co loi nghiem trong.
    [BUG-12 FIX] Don gian hoa: tra ve HybridRAG truc tiep thay vi tuple (None, HybridRAG).
    """
    from src.db.hybrid_rag import HybridRAG

    from src.shared.config import NEO4J_URI
    neo4j_uri = NEO4J_URI

    if not neo4j_uri or "dien" in neo4j_uri.lower():
        logger.warning(
            "[Main] NEO4J_URI chua duoc cau hinh trong .env.\n"
            "       -> Qdrant van hoat dong, nhung Neo4j se bi skip.\n"
            "       -> Dien thong tin Neo4j Aura vao .env de kich hoat do thi tri thuc."
        )
        # [BUG-2 FIX] HybridRAG van duoc tra ve: retrieve_context() se tu xu ly
        # loi Neo4j bang try/except graceful degradation ben trong.
        return HybridRAG()

    try:
        rag = HybridRAG()
        logger.info("[Main] HybridRAG (Qdrant + Neo4j) da san sang.")
        return rag
    except Exception as e:
        logger.error(f"[Main] Loi khoi tao HybridRAG: {e}")
        return None


def init_watcher(hybrid_rag):
    """Khoi dong InboxWatcher chay ngam."""
    from src.utils.watchdog_listener import start_watcher

    watcher = start_watcher(vault_path=VAULT_PATH, hybrid_rag=hybrid_rag)
    logger.info(f"[Main] InboxWatcher dang giam sat: {VAULT_PATH}/01_Inbox")
    return watcher


def init_core_ai(hybrid_rag):
    """
    Khoi tao cac thanh phan AI loi.
    Tra ve tuple (memory, orchestrator).
    """
    from src.core.conversation_memory import ConversationMemory
    from src.core.orchestrator import ReActOrchestrator
    from src.infrastructure.llm.openrouter_client import OpenRouterLLMClient

    memory = ConversationMemory()
    worker = OpenRouterLLMClient()
    orchestrator = ReActOrchestrator(hybrid_rag=hybrid_rag, worker=worker)

    logger.info("[Main] ConversationMemory + ReActOrchestrator da san sang.")
    return memory, orchestrator


# ==============================================================================
#  Coordinator - Diem noi giua Router va Orchestrator
# ==============================================================================
# RequestCoordinator duoc tach ra thanh src/core/coordinator.py (Sprint 1).
# main.py chi tao instance va truyen vao SpotlightWindow qua functools.partial.
# process_user_input() ben duoi chi giu lai de backward-compat voi bat ky caller cu.

from typing import Any

def process_user_input(
    user_input: Any,
    memory,
    orchestrator,
    consolidator=None,
):
    """
    Backward-compatible wrapper. Goi RequestCoordinator.process() ben trong.
    Sprint 2: Se xoa ham nay khi tat ca caller da switch sang Coordinator.
    """
    from src.core.coordinator import RequestCoordinator
    coordinator = RequestCoordinator(
        orchestrator=orchestrator,
        memory=memory,
        consolidator=consolidator,
    )
    yield from coordinator.process(user_input)


# ==============================================================================
#  Don dep tai nguyen (Graceful Shutdown)
# ==============================================================================

def _cleanup_components(components: dict):
    """Don dep tai nguyen tap trung. Goi tu ca SIGTERM va finally block."""
    # [BUG-11 FIX] Dung hotkey hook truoc tien de giai phong keyboard.wait() blocking
    if components.get("hotkey_thread"):
        try:
            components["hotkey_thread"].stop_listening()
            if not components["hotkey_thread"].wait(3000):
                components["hotkey_thread"].terminate()
        except Exception as e:
            logger.debug("[Cleanup] hotkey_thread: %s", e)

    # Don Worker Threads cua UI truoc
    if components.get("window"):
        try:
            components["window"].cleanup()
        except Exception as e:
            logger.debug("[Cleanup] window: %s", e)

    if components.get("watcher"):
        try:
            components["watcher"].stop()
        except Exception as e:
            logger.debug("[Cleanup] watcher: %s", e)

    if components.get("orchestrator"):
        try:
            components["orchestrator"].close()
        except Exception as e:
            logger.debug("[Cleanup] orchestrator: %s", e)

    if components.get("rag"):
        try:
            components["rag"].close()
        except Exception as e:
            logger.debug("[Cleanup] rag: %s", e)

    if components.get("memory_store"):
        try:
            components["memory_store"].close()
        except Exception as e:
            logger.debug("[Cleanup] memory_store: %s", e)

    if components.get("consolidator"):
        try:
            components["consolidator"].stop_scheduler()
        except Exception as e:
            logger.debug("[Cleanup] consolidator: %s", e)

    gc.collect()
    logger.info("[Main] Da don sach tai nguyen.")



def create_shutdown_handler(components: dict):
    """Tao ham xu ly tin hieu SIGTERM de don dep tai nguyen."""
    def shutdown(signum, frame):
        logger.info("[Main] Nhan tin hieu dung. Dang don dep...")
        _cleanup_components(components)
        logger.info("[Main] He thong da dung an toan. Tam biet!")
        sys.exit(0)
    return shutdown


# ==============================================================================
#  MAIN - Entry Point tich hop PyQt6 (Giai doan 4)
# ==============================================================================

def main():
    logger.info("=" * 60)
    logger.info("  Digital Scholar - Agent V5.0")
    logger.info("  Voice: GeminiSTT (Cloud API) | TTS: edge-tts | UI: PyQt6 Spotlight")
    logger.info("=" * 60)

    components = {}

    # -- Buoc 1: Khoi tao Database --
    logger.info("[Main] [1/4] Dang ket noi Database...")
    rag = init_database()   # [BUG-12 FIX] Tra ve HybridRAG truc tiep, khong con tuple
    components["rag"] = rag

    # -- Buoc 2: Khoi dong InboxWatcher --
    logger.info("[Main] [2/4] Dang khoi dong InboxWatcher...")
    # [B9-FIX] Chi khoi dong watcher neu rag khong phai None
    if rag is not None:
        try:
            watcher = init_watcher(rag)
            components["watcher"] = watcher
        except Exception as e:
            logger.error(f"[Main] Loi khoi dong Watcher: {e}")
    else:
        logger.warning("[Main] Bo qua InboxWatcher vi Database khong san sang.")

    # -- Buoc 3: Khoi tao Core AI --
    logger.info("[Main] [3/4] Dang khoi tao Core AI...")
    memory = orchestrator = None
    # [B9-FIX] Chi khoi tao Core AI neu rag khong phai None
    if rag is not None:
        try:
            memory, orchestrator = init_core_ai(rag)
            components["memory"]       = memory
            components["orchestrator"] = orchestrator
            
            # Khoi tao MemoryConsolidator
            from src.services.memory_consolidator import MemoryConsolidator
            from src.shared.config import GEMINI_API_KEY
            from src.db.memory_store import SQLiteMemoryStore

            # Tao SQLiteMemoryStore (luu tai AppData/Local/DigitalScholar/memory.db)
            memory_store = SQLiteMemoryStore()
            components["memory_store"] = memory_store

            # Khoi tao MemoryConsolidator voi IMemoryStore thay vi vault_path
            consolidator = MemoryConsolidator(
                memory=memory,
                memory_store=memory_store,
                gemini_api_key=GEMINI_API_KEY,
            )
            components["consolidator"] = consolidator
            consolidator.start_scheduler()
            
        except Exception as e:
            logger.error(f"[Main] Loi khoi tao Core AI / Consolidator: {e}")
    else:
        logger.warning("[Main] Bo qua Core AI vi Database khong san sang.")

    # Dang ky SIGTERM va SIGINT (Ctrl+C) handler
    shutdown_handler = create_shutdown_handler(components)
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # -- Buoc 4: Khoi chay Spotlight UI (PyQt6) --
    logger.info("[Main] [4/4] Dang khoi tao Spotlight UI (PyQt6)...")
    exit_code = 0

    try:
        from PyQt6.QtWidgets import QApplication
        from src.ui.spotlight import SpotlightWindow, GlobalHotkeyWorker
        from src.ui.tray import setup_system_tray
        from src.core.semantic_interceptor import SemanticInterceptor
        # Tao Qt Application
        # setQuitOnLastWindowClosed(False): app song khi cua so dong (chay ngam qua tray)
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName("Digital Scholar")

        # [VOICE] GeminiSTT duoc khoi tao lazy (lan dau tien ghi am moi load)
        # Khong con subprocess Whisper Server nao duoc khoi dong o day
        logger.info("[Main] Voice Engine: GeminiSTT (Gemini Cloud API) san sang theo Lazy Init.")

        # Dong goi process_fn de Spotlight goi khong can biet tham so
        if memory is not None and orchestrator is not None:
            process_fn = functools.partial(
                process_user_input,
                memory=memory,
                orchestrator=orchestrator,
                consolidator=components.get("consolidator"),
            )
            logger.info("[Main] Core AI san sang phuc vu cau hoi.")
        else:
            logger.warning("[Main] Core AI chua san sang (kiem tra API Keys trong .env).")
            process_fn = None

        # Khoi tao SemanticInterceptor, tai su dung model e5-base tu Qdrant
        if rag is not None:
            embed_func = rag.qdrant.embed_text
        else:
            # Fallback chong loi khi khong co database
            embed_func = lambda x: [0.0] * 768
            
        # SemanticInterceptor nhan memory_store (IMemoryStore) de luu ghi chu nhanh
        memory_store = components.get("memory_store")
        semantic_interceptor = SemanticInterceptor(
            embed_func=embed_func,
            memory_store=memory_store,
        )

        # intercept_fn: bo vault_path partial (khong con dung)
        intercept_fn = semantic_interceptor.intercept

        # Tao cua so Spotlight (khong con truyen vault_path cho memory, chi cho watchdog)
        window = SpotlightWindow(
            process_fn=process_fn,
            intercept_fn=intercept_fn,
        )
        components["window"] = window   # Luu de cleanup() goi khi SIGTERM

        # Thiet lap System Tray Icon
        tray = setup_system_tray(app, window)
        components["tray"] = tray

        # Khoi dong Global Hotkey Worker (Ctrl+Space)
        # LUU Y: Can quyen Administrator tren Windows de hook toan cuc
        hotkey_thread = GlobalHotkeyWorker(parent=app)
        hotkey_thread.sig_toggle.connect(window.toggle_visibility)
        hotkey_thread.sig_voice.connect(window.toggle_voice_recording)  # VAD mode
        hotkey_thread.sig_ptt_start.connect(window._on_ptt_start)       # [S2-PTT]
        hotkey_thread.sig_ptt_stop.connect(window._on_ptt_stop)         # [S2-PTT]
        hotkey_thread.start()
        components["hotkey_thread"] = hotkey_thread

        # Thong bao san sang
        logger.info("=" * 60)
        logger.info("  Digital Scholar dang chay ngam.")
        logger.info(f"  Inbox: {os.path.join(VAULT_PATH, '01_Inbox')}")
        logger.info("  Core AI: " + ("SAN SANG" if process_fn else "CHUA CO API KEY"))
        logger.info("  Phim tat: Ctrl+Space de bat/tat Spotlight.")
        logger.info("  Phim tat: Ctrl+Shift+Space de bat/tat thu am (Voice Mode).")
        logger.info("  Click phai System Tray -> Thoat de dung han.")
        logger.info("=" * 60)

        # [B24-FIX] check_and_catchup() goi Gemini API dong bo -> lam cham boot
        # -> Dua vao QTimer.singleShot(2000) de chay sau khi UI da san sang
        consolidator = components.get("consolidator")
        if consolidator:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: consolidator.check_and_catchup())

        # [FIX] QTimer dummy de PyQt6 nhuong CPU cho Python bat tin hieu Ctrl+C tu terminal
        from PyQt6.QtCore import QTimer
        dummy_timer = QTimer()
        dummy_timer.timeout.connect(lambda: None)
        dummy_timer.start(500)

        # Chay Qt Event Loop (thay the while True: time.sleep(1) cua Giai doan 3)
        exit_code = app.exec()

    except ImportError as e:
        # PyQt6 chua cai -> fallback daemon loop khong co UI
        logger.error(f"[Main] PyQt6 chua cai: {e}")
        logger.warning("[Main] Fallback: chay daemon khong co UI.")
        logger.info("  Inbox: " + os.path.join(VAULT_PATH, "01_Inbox"))
        logger.info("  Core AI: " + ("SAN SANG" if orchestrator else "CHUA CO API KEY"))
        logger.info("  Nhan Ctrl+C de dung he thong.")
        try:
            import threading
            threading.Event().wait()
        except KeyboardInterrupt:
            pass

    except Exception as e:
        logger.error(f"[Main] Loi khoi tao UI: {e}")
        exit_code = 1

    finally:
        _cleanup_components(components)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
