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
    Khoi tao cac thanh phan AI loi (Giai doan 3).
    Tra ve tuple (router, memory, orchestrator).
    """
    from src.core.semantic_router import SemanticRouter, ConversationMemory
    from src.core.orchestrator import ReActOrchestrator

    router = SemanticRouter()
    memory = ConversationMemory()
    orchestrator = ReActOrchestrator(hybrid_rag=hybrid_rag)

    logger.info("[Main] SemanticRouter + ReActOrchestrator da san sang.")
    return router, memory, orchestrator


# ==============================================================================
#  Coordinator - Diem noi giua Router va Orchestrator (Giu nguyen tu Giai doan 3)
# ==============================================================================

def process_user_input(
    user_input: str,
    router,
    memory,
    orchestrator,
    consolidator=None,
) -> str:
    """
    Coordinator trung tam ket noi toan bo luong xu ly cau hoi.

    Luong dieu phoi:
      user_input
        -> SemanticRouter.route()  -> Phan loai intent
        -> [research_query]        -> ReActOrchestrator.run()
        -> [os_control]            -> Da xu ly truoc boi RegexInterceptor
        -> [export_docx]           -> Placeholder (Giai doan 5)
        -> [daily_task]            -> Placeholder (Giai doan 5)
        -> memory.add(Q, A)        -> Cap nhat Sliding Window
        -> return answer
    """
    try:
        intent = router.route(user_input=user_input, memory=memory)
        logger.info(f"[Coordinator] Intent: {intent.intent_type}")

        if intent.intent_type == "research_query":
            answer = orchestrator.run(user_input=user_input)

        elif intent.intent_type == "os_control":
            payload = intent.os_action_payload
            app_name = payload.app_name if payload else "unknown"
            answer = f"Lệnh mở '{app_name}' đã được ghi nhận."

        elif intent.intent_type == "export_docx":
            # [C4-FIX] Guard None: topic có thể là None nếu router không nhận diện được
            topic = intent.topic or "không xác định"
            try:
                from src.services.docx_exporter import DocxExporter
                exporter = DocxExporter(orchestrator=orchestrator)
                _path, answer = exporter.export(topic=topic)
            except ImportError:
                answer = f"Xuất báo cáo về '{topic}': thiếu thư viện python-docx. Chạy: pip install python-docx"
            except Exception as e:
                logger.error("[Coordinator] Lỗi DocxExporter: %s", e)
                answer = f"Lỗi xuất báo cáo: {str(e)[:100]}"

        elif intent.intent_type == "daily_task":
            # Gọi hàm run_consolidation của Consolidator (chạy trong AIWorker thread)
            try:
                from src.services.memory_consolidator import MemoryConsolidator
                # Ta cần tạo 1 instance tạm (nếu không được pass vào) hoặc
                # tốt nhất là truyền consolidator vào process_user_input.
                # Tuy nhiên, do process_user_input chưa có consolidator, ta sẽ
                # thêm tham số consolidator vào functools.partial.
                if consolidator:
                    consolidator.run_consolidation(is_catchup=False)
                    answer = "Đã tổng hợp bộ nhớ ngắn hạn và lưu vào Profile.md thành công!"
                else:
                    answer = "Hệ thống tổng hợp bộ nhớ chưa sẵn sàng."
            except Exception as e:
                logger.error("[Coordinator] Lỗi tổng hợp bộ nhớ: %s", e)
                answer = f"Lỗi tổng hợp bộ nhớ: {str(e)[:100]}"

        else:
            answer = orchestrator.run(user_input=user_input)

        memory.add(user_input=user_input, agent_response=answer)
        return answer

    except Exception as e:
        error_msg = f"He thong gap su co: {str(e)[:100]}"
        logger.error(f"[Coordinator] Loi: {e}")
        try:
            memory.add(user_input=user_input, agent_response=error_msg)
        except Exception:
            pass
        return error_msg


# ==============================================================================
#  Don dep tai nguyen (Graceful Shutdown)
# ==============================================================================

def _cleanup_components(components: dict):
    """Don dep tai nguyen tap trung. Goi tu ca SIGTERM va finally block."""
    # [BUG-11 FIX] Dung hotkey hook truoc tien de giai phong keyboard.wait() blocking
    if components.get("hotkey_thread"):
        try:
            components["hotkey_thread"].stop_listening()
            components["hotkey_thread"].wait(500)
        except Exception:
            pass

    # Don Worker Threads cua UI truoc
    if components.get("window"):
        try:
            components["window"].cleanup()
        except Exception:
            pass

    if components.get("watcher"):
        try:
            components["watcher"].stop()
        except Exception:
            pass

    if components.get("orchestrator"):
        try:
            components["orchestrator"].close()
        except Exception:
            pass

    if components.get("rag"):
        try:
            components["rag"].close()
        except Exception:
            pass

    if components.get("consolidator"):
        try:
            components["consolidator"].stop_scheduler()
        except Exception:
            pass

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
    logger.info("  Digital Scholar - Last Agent V3.0")
    logger.info("  Giai doan 4: Spotlight UI + Zero-Cost Interceptor")
    logger.info("=" * 60)

    components = {}

    # -- Buoc 1: Khoi tao Database --
    logger.info("[Main] [1/4] Dang ket noi Database...")
    rag = init_database()   # [BUG-12 FIX] Tra ve HybridRAG truc tiep, khong con tuple
    components["rag"] = rag

    # -- Buoc 2: Khoi dong InboxWatcher --
    logger.info("[Main] [2/4] Dang khoi dong InboxWatcher...")
    try:
        watcher = init_watcher(rag)
        components["watcher"] = watcher
    except Exception as e:
        logger.error(f"[Main] Loi khoi dong Watcher: {e}")

    # -- Buoc 3: Khoi tao Core AI --
    logger.info("[Main] [3/4] Dang khoi tao Core AI...")
    router = memory = orchestrator = None
    try:
        router, memory, orchestrator = init_core_ai(rag)
        components["router"]       = router
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
        
        # Check catchup va khoi dong scheduler (0:00 midnight)
        consolidator.check_and_catchup()
        consolidator.start_scheduler()
        
    except Exception as e:
        logger.error(f"[Main] Loi khoi tao Core AI / Consolidator: {e}")

    # Dang ky SIGTERM handler
    signal.signal(signal.SIGTERM, create_shutdown_handler(components))

    # -- Buoc 4: Khoi chay Spotlight UI (PyQt6) --
    logger.info("[Main] [4/4] Dang khoi tao Spotlight UI (PyQt6)...")
    exit_code = 0

    try:
        from PyQt6.QtWidgets import QApplication
        from src.ui.spotlight import SpotlightWindow, GlobalHotkeyThread, setup_system_tray
        from src.core.regex_interceptor import intercept as regex_intercept

        # Tao Qt Application
        # setQuitOnLastWindowClosed(False): app song khi cua so dong (chay ngam qua tray)
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName("Digital Scholar")

        # Dong goi process_fn de Spotlight goi khong can biet tham so
        if router and memory and orchestrator:
            process_fn = functools.partial(
                process_user_input,
                router=router,
                memory=memory,
                orchestrator=orchestrator,
                consolidator=components.get("consolidator"),
            )
            logger.info("[Main] Core AI san sang phuc vu cau hoi.")
        else:
            logger.warning("[Main] Core AI chua san sang (kiem tra API Keys trong .env).")
            process_fn = None

        # Dong goi intercept_fn voi vault_path co san
        intercept_fn = functools.partial(regex_intercept, vault_path=VAULT_PATH)

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

        # Khoi dong Global Hotkey Thread (Ctrl+Space)
        # LUU Y: Can quyen Administrator tren Windows de hook toan cuc
        hotkey_thread = GlobalHotkeyThread(parent=app)
        hotkey_thread.toggle_signal.connect(window.toggle_visibility)
        hotkey_thread.voice_signal.connect(window.toggle_voice_recording)
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
            while True:
                time.sleep(1)
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
