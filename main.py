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
import time
import signal
import logging
import gc
import functools
from pathlib import Path

from dotenv import load_dotenv

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

# --- Tai bien moi truong ---
load_dotenv()

# --- Duong dan Obsidian Vault ---
VAULT_PATH = os.getenv(
    "OBSIDIAN_VAULT_PATH",
    os.path.join(os.path.dirname(__file__), "Obsidian_Vault"),
)


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

    neo4j_uri = os.getenv("NEO4J_URI", "")

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

    memory = ConversationMemory()
    orchestrator = ReActOrchestrator(hybrid_rag=hybrid_rag)

    logger.info("[Main] ConversationMemory + ReActOrchestrator da san sang.")
    return memory, orchestrator


# ==============================================================================
#  Coordinator - Diem noi giua Router va Orchestrator (Giu nguyen tu Giai doan 3)
# ==============================================================================

from typing import Any

def process_user_input(
    user_input: Any,
    memory,
    orchestrator,
    consolidator=None,
):
    """
    Coordinator trung tam ket noi toan bo luong xu ly cau hoi.
    Giai doan 5.5: Dynamic Routing (Bypass SemanticRouter cu)
    """
    try:
        if isinstance(user_input, dict):
            intent_type = user_input.get("intent", "research_query")
            query = user_input.get("query", "")
            topic = user_input.get("topic", "")
        else:
            intent_type = "research_query"
            query = str(user_input)
            topic = ""

        logger.info(f"[Coordinator] Intent (Dynamic): {intent_type}")

        if intent_type == "EXPORT_DOCX":
            topic_str = topic or query
            try:
                from src.services.docx_exporter import DocxExporter
                exporter = DocxExporter(orchestrator=orchestrator)
                _path, answer = exporter.export(topic=topic_str)
                yield answer
            except ImportError:
                yield f"Xuất báo cáo về '{topic_str}': thiếu thư viện python-docx. Chạy: pip install python-docx"
            except Exception as e:
                logger.error("[Coordinator] Lỗi DocxExporter: %s", e, exc_info=True)
                yield f"Lỗi xuất báo cáo: {str(e)[:100]}"
                
        else:
            # intent_type sẽ là "daily_task" hoặc "research_query"
            gen = orchestrator.run(user_input=query, intent=intent_type)
            full_answer = ""
            if isinstance(gen, str):
                 full_answer = gen
                 yield gen
            else:
                 for chunk in gen:
                      if chunk:
                          full_answer += chunk
                          yield chunk
            
            if full_answer:
                memory.add(user_input=query, agent_response=full_answer)

    except Exception as e:
        logger.error(f"[Coordinator] Lỗi xử lý: {e}", exc_info=True)
        yield f"Lỗi hệ thống: {str(e)}"


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

    if components.get("consolidator"):
        try:
            components["consolidator"].stop_scheduler()
        except Exception as e:
            logger.debug("[Cleanup] consolidator: %s", e)

    # [WHISPER DAEMON] Don dep Microservice
    if components.get("whisper_server"):
        try:
            port_file = os.path.join("temp", ".whisper_port")
            if os.path.exists(port_file):
                with open(port_file, "r") as f:
                    port = int(f.read().strip())
                import urllib.request
                urllib.request.urlopen(f"http://127.0.0.1:{port}/shutdown", timeout=1.0)
        except Exception as e:
            logger.debug("[Cleanup] whisper shutdown: %s", e)
        # Hard kill (Bao hiem Zombie Process)
        try:
            components["whisper_server"].terminate()
        except Exception as e:
            logger.debug("[Cleanup] whisper terminate: %s", e)

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
    logger.info("  Digital Scholar - Agent V4.0")
    logger.info("  Giai doan 4: Spotlight UI + Zero-Cost Interceptor")
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
            gemini_api_key = os.getenv("GEMINI_API_KEY", "")
            consolidator = MemoryConsolidator(
                memory=memory, 
                vault_path=VAULT_PATH, 
                gemini_api_key=gemini_api_key
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
        from src.ui.spotlight import SpotlightWindow, GlobalHotkeyWorker, setup_system_tray
        from src.core.semantic_interceptor import SemanticInterceptor
        # Tao Qt Application
        # setQuitOnLastWindowClosed(False): app song khi cua so dong (chay ngam qua tray)
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName("Digital Scholar")

        # Khoi dong ngam Whisper Server (Daemon Microservice)
        import subprocess
        try:
            whisper_proc = subprocess.Popen([sys.executable, "src/api/whisper_server.py"])
            components["whisper_server"] = whisper_proc
            logger.info(f"[Main] Khoi dong ngam Whisper Server (PID: {whisper_proc.pid})")
        except Exception as e:
            logger.error(f"[Main] Khong the khoi dong Whisper Server: {e}")

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
            
        semantic_interceptor = SemanticInterceptor(embed_func=embed_func)

        # Dong goi intercept_fn voi vault_path co san
        intercept_fn = functools.partial(semantic_interceptor.intercept, vault_path=VAULT_PATH)

        # Tao cua so Spotlight
        window = SpotlightWindow(
            process_fn=process_fn,
            intercept_fn=intercept_fn,
            vault_path=VAULT_PATH,
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
