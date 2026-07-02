"""
main.py - Điểm Khởi chạy Background Daemon (Entry Point)
=========================================================
Luồng khởi động:
  1. Load cấu hình từ .env
  2. Khởi tạo HybridRAG (Qdrant Local + Neo4j Cloud) - lazy init
  3. Khởi động InboxWatcher chạy ngầm giám sát 01_Inbox/
  4. [Giai đoạn 4] Khởi chạy Spotlight UI (PyQt6) - sẽ thêm sau
  5. Giữ tiến trình sống mãi cho đến khi nhận tín hiệu tắt (Ctrl+C / SIGTERM)

Yêu cầu hệ thống:
  - Chạy với quyền Administrator để bắt phím tắt toàn cục (keyboard library).
  - File .env phải được điền đầy đủ trước khi chạy (xem README.md).
"""

import os
import sys
import time
import signal
import logging
import gc
from pathlib import Path

from dotenv import load_dotenv

# ─── Cấu hình Logging toàn cục ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Ghi log ra file để debug Production
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("Main")

# ─── Tải biến môi trường ───────────────────────────────────────────────────────
load_dotenv()

# ─── Đường dẫn Obsidian Vault ─────────────────────────────────────────────────
# Ưu tiên đọc từ .env, dự phòng dùng thư mục Obsidian_Vault trong dự án
VAULT_PATH = os.getenv(
    "OBSIDIAN_VAULT_PATH",
    os.path.join(os.path.dirname(__file__), "Obsidian_Vault"),
)


# ══════════════════════════════════════════════════════════════════════════════
#  Khởi tạo các thành phần hệ thống
# ══════════════════════════════════════════════════════════════════════════════
def init_database():
    """
    Khởi tạo kết nối HybridRAG (Qdrant + Neo4j).
    Trả về instance HybridRAG hoặc None nếu config chưa sẵn sàng.
    """
    from src.db.hybrid_rag import HybridRAG

    neo4j_uri = os.getenv("NEO4J_URI", "")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "")

    # Kiểm tra config Neo4j
    if not neo4j_uri or "điền" in neo4j_uri.lower():
        logger.warning(
            "[Main] NEO4J_URI chưa được cấu hình trong .env.\n"
            "       -> Qdrant vẫn hoạt động, nhưng Neo4j sẽ bị skip.\n"
            "       -> Điền thông tin Neo4j Aura vào .env để kích hoạt đồ thị tri thức."
        )
        return None, HybridRAG()

    try:
        rag = HybridRAG()
        logger.info("[Main] ✅ HybridRAG (Qdrant + Neo4j) đã sẵn sàng.")
        return None, rag
    except Exception as e:
        logger.error(f"[Main] ❌ Lỗi khởi tạo HybridRAG: {e}")
        return None, None


def init_watcher(hybrid_rag):
    """Khởi động InboxWatcher chạy ngầm."""
    from src.utils.watchdog_listener import start_watcher

    watcher = start_watcher(vault_path=VAULT_PATH, hybrid_rag=hybrid_rag)
    logger.info(f"[Main] InboxWatcher dang giam sat: {VAULT_PATH}/01_Inbox")
    return watcher


def init_core_ai(hybrid_rag):
    """
    Khởi tạo các thành phần AI lõi (Giai đoạn 3).
    Trả về tuple (router, orchestrator) sẵn sàng phục vụ câu hỏi.
    """
    from src.core.semantic_router import SemanticRouter, ConversationMemory
    from src.core.orchestrator import ReActOrchestrator

    router = SemanticRouter()
    memory = ConversationMemory()  # Sliding Window N=5, shared across calls
    orchestrator = ReActOrchestrator(hybrid_rag=hybrid_rag)

    logger.info("[Main] SemanticRouter + ReActOrchestrator da san sang.")
    return router, memory, orchestrator


# ══════════════════════════════════════════════════════════════════════════════
#  Coordinator - Điểm nối giữa Router và Orchestrator
# ══════════════════════════════════════════════════════════════════════════════
def process_user_input(
    user_input: str,
    router,
    memory,
    orchestrator,
) -> str:
    """
    Coordinator trung tâm kết nối toàn bộ luồng xử lý câu hỏi.

    Luồng điệu phối:
      user_input
        ↓
      SemanticRouter.route()     -> Phân loại intent + trích xuất keywords
        ↓
      [research_query]           -> ReActOrchestrator.run() -> answer
      [os_control]               -> Placeholder (Giai đoạn 4 thêm OS automation)
      [export_docx]              -> Placeholder (Giai đoạn 5 thêm Word exporter)
      [daily_task]               -> Placeholder (Giai đoạn 4 thêm APScheduler)
        ↓
      memory.add(Q, A)           -> Cập nhật Sliding Window
        ↓
      return answer
    """
    try:
        # Bước 1: Semantic Router phân loại ý định
        intent = router.route(user_input=user_input, memory=memory)
        logger.info(f"[Coordinator] Intent: {intent.intent_type}")

        # Bước 2: Rẽ nhánh theo loại intent
        if intent.intent_type == "research_query":
            answer = orchestrator.run(user_input=user_input)

        elif intent.intent_type == "os_control":
            # Placeholder - sẽ triển khai ở Giai đoạn 4 (Spotlight UI + keyboard hook)
            payload = intent.os_action_payload
            app = payload.app_name if payload else "unknown"
            answer = f"[OS Control] Lenh mo '{app}' da duoc ghi nhan. Chuc nang se kha dung o Giai doan 4."

        elif intent.intent_type == "export_docx":
            # Placeholder - sẽ triển khai ở Giai đoạn 5 (Word Exporter)
            answer = f"[Export] Xuat bao cao chu de '{intent.topic}' se kha dung o Giai doan 5."

        elif intent.intent_type == "daily_task":
            # Placeholder - sẽ triển khai ở Giai đoạn 4 (APScheduler)
            answer = "[Daily Task] Tac vu hang ngay se kha dung o Giai doan 4."

        else:
            # Fallback: luôn chạy qua Orchestrator nếu không xác định được intent
            answer = orchestrator.run(user_input=user_input)

        # Bước 3: Cập nhật Sliding Window memory
        memory.add(user_input=user_input, agent_response=answer)
        return answer

    except Exception as e:
        error_msg = f"He thong gap su co khi xu ly cau hoi: {str(e)[:100]}"
        logger.error(f"[Coordinator] Loi: {e}")
        # Vẫn cập nhật memory với thông báo lỗi để giữ liên tục
        memory.add(user_input=user_input, agent_response=error_msg)
        return error_msg


# ══════════════════════════════════════════════════════════════════════════════
#  Xử lý tín hiệu dừng hệ thống (Graceful Shutdown)
# ══════════════════════════════════════════════════════════════════════════════
def create_shutdown_handler(components: dict):
    """
    Tạo hàm xử lý tín hiệu SIGINT/SIGTERM để dọn dẹp tài nguyên sạch sẽ.
    """
    def shutdown(signum, frame):
        logger.info("[Main] Nhan tin hieu dung. Dang don dep...")

        if components.get("watcher"):
            components["watcher"].stop()

        if components.get("orchestrator"):
            components["orchestrator"].close()

        if components.get("rag"):
            components["rag"].close()

        gc.collect()
        logger.info("[Main] He thong da dung an toan. Tam biet!")
        sys.exit(0)

    return shutdown


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    logger.info("=" * 60)
    logger.info("  Digital Scholar - Last Agent V3.0")
    logger.info("  Khoi dong he thong Background Daemon...")
    logger.info("=" * 60)

    components = {}

    # --- Buoc 1: Khoi tao Database ---
    logger.info("[Main] [1/4] Dang ket noi Database...")
    _, rag = init_database()
    components["rag"] = rag

    # --- Buoc 2: Khoi dong InboxWatcher ---
    logger.info("[Main] [2/4] Dang khoi dong InboxWatcher...")
    try:
        watcher = init_watcher(rag)
        components["watcher"] = watcher
    except Exception as e:
        logger.error(f"[Main] Loi khoi dong Watcher: {e}")

    # --- Buoc 3: Khoi tao Core AI (SemanticRouter + ReActOrchestrator) ---
    logger.info("[Main] [3/4] Dang khoi tao Core AI...")
    try:
        router, memory, orchestrator = init_core_ai(rag)
        components["router"] = router
        components["memory"] = memory
        components["orchestrator"] = orchestrator
    except Exception as e:
        logger.error(f"[Main] Loi khoi tao Core AI: {e}")
        router = memory = orchestrator = None

    # --- Buoc 4: [Placeholder] Spotlight UI - Giai doan 4 ---
    logger.info("[Main] [4/4] Spotlight UI: Chua kha dung (Giai doan 4).")

    # --- Dang ky Graceful Shutdown ---
    shutdown_handler = create_shutdown_handler(components)
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # --- Thong bao he thong san sang ---
    logger.info("=" * 60)
    logger.info("  Digital Scholar dang chay ngam.")
    logger.info(f"  Inbox: {os.path.join(VAULT_PATH, '01_Inbox')}")
    logger.info("  Router + Orchestrator: " + ("SAN SANG" if orchestrator else "CHUA CO API KEY"))
    logger.info("  Nhan Ctrl+C de dung he thong.")
    logger.info("=" * 60)

    # --- Giu tien trinh chay mai ---
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
