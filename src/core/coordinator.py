"""
src/core/coordinator.py — RequestCoordinator
==============================================
Tách từ main.py: process_user_input() → RequestCoordinator.

Vai trò:
  - Điều phối request từ UI (SpotlightWindow) đến đúng handler
  - Routing intent: EXPORT_DOCX → DocxExporter, khác → Orchestrator
  - Thêm conversation history vào context trước khi gọi Orchestrator
  - Ghi lại memory sau khi nhận response đầy đủ

Layer: Application (src/core/) — KHÔNG import Presentation (src/ui/).
"""
import logging
from typing import Generator, Optional, Any

logger = logging.getLogger("Coordinator")


class RequestCoordinator:
    """
    Điểm kết nối giữa UI layer và Application layer.

    Trách nhiệm duy nhất:
      - Nhận request từ SpotlightWindow
      - Route đến đúng handler (DocxExporter / Orchestrator)
      - Orchestrate memory: đọc context_history trước, ghi sau khi có response

    KHÔNG chứa logic AI, KHÔNG import QWidget, KHÔNG chứa prompt.
    """

    def __init__(self, orchestrator, memory, consolidator=None):
        """
        Args:
            orchestrator: ReActOrchestrator instance (dependency injection từ main.py)
            memory      : ConversationMemory instance
            consolidator: MemoryConsolidator instance (optional)
        """
        self._orchestrator = orchestrator
        self._memory = memory
        self._consolidator = consolidator

    def process(self, user_input: Any) -> Generator[str, None, None]:
        """
        Entry point duy nhất từ UI: nhận request và dispatch đến đúng handler.

        Args:
            user_input: str (câu hỏi thuần) hoặc dict {intent, query, topic}

        Yields:
            str: chunks câu trả lời để stream lên UI
        """
        try:
            intent_type, query, topic = self._parse_input(user_input)
            logger.info("[Coordinator] Intent: %s | Query: %s...", intent_type, query[:60])

            if intent_type == "EXPORT_DOCX":
                yield from self._handle_export(topic or query)
            else:
                yield from self._handle_query(query, intent_type)

        except Exception as e:
            logger.error("[Coordinator] Lỗi xử lý: %s", e, exc_info=True)
            yield f"Lỗi hệ thống: {str(e)}"

    def _parse_input(self, user_input: Any) -> tuple[str, str, str]:
        """
        Chuẩn hóa user_input thành (intent_type, query, topic).

        Hỗ trợ:
          - str: "câu hỏi thuần" → intent=research_query
          - dict: {"intent": ..., "query": ..., "topic": ...}
        """
        if isinstance(user_input, dict):
            intent_type = user_input.get("intent", "research_query")
            query = user_input.get("query", "")
            topic = user_input.get("topic", "")
        else:
            intent_type = "research_query"
            query = str(user_input)
            topic = ""
        return intent_type, query, topic

    def _handle_export(self, topic: str) -> Generator[str, None, None]:
        """Handler cho EXPORT_DOCX intent."""
        try:
            from src.services.docx_exporter import DocxExporter
            exporter = DocxExporter(orchestrator=self._orchestrator)
            _path, answer = exporter.export(topic=topic)
            yield answer
        except ImportError:
            yield (
                f"Xuất báo cáo về '{topic}': thiếu thư viện python-docx. "
                "Chạy: pip install python-docx"
            )
        except Exception as e:
            logger.error("[Coordinator] Lỗi DocxExporter: %s", e, exc_info=True)
            yield f"Lỗi xuất báo cáo: {str(e)[:100]}"

    def _handle_query(self, query: str, intent_type: str) -> Generator[str, None, None]:
        """
        Handler cho research_query và daily_task.

        Flow:
          1. Chạy Orchestrator (streaming)
          2. Thu thập full_answer
          3. Ghi vào ConversationMemory sau khi stream xong
        """
        gen = self._orchestrator.run(user_input=query, intent=intent_type)
        full_answer = ""

        if isinstance(gen, str):
            # Non-streaming fallback
            full_answer = gen
            yield gen
        else:
            for chunk in gen:
                if chunk:
                    full_answer += chunk
                    yield chunk

        # Ghi memory SAU khi đã stream xong toàn bộ response
        if full_answer and self._memory is not None:
            try:
                self._memory.add(user_input=query, agent_response=full_answer)
            except Exception as e:
                logger.warning("[Coordinator] Không ghi được memory: %s", e)
