"""
src/core/prompt_builder.py — Centralized Prompt Management
===========================================================
Single source of truth cho tất cả prompt templates trong hệ thống.

Trước đây prompt rải rác tại 4 nơi:
  - orchestrator.py    : _ANSWER_SYSTEM_PROMPT, _CRITIQUE_SYSTEM_PROMPT, fast-track inline
  - memory_consolidator.py : _REDUCE_SYSTEM_PROMPT
  - docx_exporter.py   : report generation prompt
  - parser.py          : PPTX cleanup prompt

ADR-006: PromptBuilder class thay vì prompts/ directory.
Lý do: 4 prompts hiện tại → 1 class đủ gọn. Directory phù hợp hơn khi có 10+ prompt files.

Hướng phát triển tương lai (Sprint 4+):
  PromptTemplate → PromptRenderer → PromptBuilder  (khi cần i18n, versioning, A/B testing)
"""
from dataclasses import dataclass, field
from typing import Optional


# ─── Context DTO ──────────────────────────────────────────────────────────────

@dataclass
class PromptContext:
    """
    Data Transfer Object chứa tất cả input cần thiết để build prompt.
    Truyền qua đây thay vì nhiều string arguments rời rạc.
    """
    user_query: str
    """Câu hỏi gốc của người dùng."""

    rag_context: str = ""
    """Nội dung chunks từ HybridRAG.retrieve_context() — đã được format."""

    web_context: str = ""
    """Kết quả DuckDuckGo web search — đã được format."""

    conversation_history: str = ""
    """
    Lịch sử hội thoại từ ConversationMemory.get_context_string().
    Fix V8: trường này đảm bảo memory thực sự được đưa vào prompt.
    """

    doc_sources: list = field(default_factory=list)
    """Danh sách tên file tài liệu nguồn (cho citation)."""


# ─── System Prompt Templates ──────────────────────────────────────────────────

class PromptBuilder:
    """
    Trung tâm quản lý tất cả prompt templates của Digital Scholar.

    Usage:
        ctx = PromptContext(user_query="...", rag_context="...", conversation_history="...")
        system, user = PromptBuilder.build_answer(ctx)
        # → truyền vào WorkerEngine.generate(system_prompt=system, user_prompt=user)

    Lưu ý: Hiện tại dùng @classmethod để đơn giản (Sprint 1).
    Nâng cấp sang PromptTemplate/PromptRenderer khi cần A/B test hoặc i18n (Sprint 4+).
    """

    # ── Tier 1: Answer Generation (WorkerEngine via OpenRouter) ───────────────

    RESEARCH_SYSTEM: str = (
        "Bạn là Digital Scholar - trợ lý nghiên cứu học thuật chuyên nghiệp.\n"
        "Nhiệm vụ: Dựa vào NGỮ CẢNH được cung cấp, trả lời câu hỏi bằng tiếng Việt học thuật mượt mà.\n"
        "Quy tắc:\n"
        "- Ưu tiên thông tin từ ngữ cảnh. Nếu ngữ cảnh thiếu, dùng kiến thức chung có ghi chú.\n"
        "- Sử dụng thuật ngữ học thuật chính xác.\n"
        "- Trình bày rõ ràng, mạch lạc. Không trả lời mơ hồ.\n"
        "- KHÔNG bịa đặt số liệu hay trích dẫn không có trong ngữ cảnh.\n"
        "- Nếu có LỊCH SỬ HỘI THOẠI, hãy dùng nó để hiểu ngữ cảnh câu hỏi hiện tại."
    )

    FAST_SYSTEM: str = (
        "Bạn là trợ lý ảo thông minh. Trả lời ngắn gọn, trực tiếp vào trọng tâm bằng tiếng Việt.\n"
        "Nếu có NGỮ CẢNH, ưu tiên dùng. Nếu không đủ, dùng kiến thức chung.\n"
        "Nếu có LỊCH SỬ HỘI THOẠI, tham khảo để hiểu câu hỏi hiện tại."
    )

    # ── Tier 2: Self-Critique (SelfCritiqueAgent via Gemini Flash) ────────────

    CRITIQUE_SYSTEM: str = (
        "Bạn là bộ chấm điểm chất lượng ngữ cảnh (Self-Critique Agent).\n"
        "Nhiệm vụ: Đánh giá mức độ phù hợp của NGỮ CẢNH RAG với CÂU HỎI người dùng.\n"
        "Trả về JSON theo cấu trúc sau, KHÔNG thêm giải thích, KHÔNG dùng markdown:\n"
        "{\n"
        '  "relevance_score": <số thực 0.0-10.0>,\n'
        '  "answerability_score": <số thực 0.0-10.0>,\n'
        '  "missing_information": "<mô tả ngắn gọn phần còn thiếu hoặc empty string>",\n'
        '  "action_required": "proceed" | "force_web_search"\n'
        "}\n"
        "Quy tắc:\n"
        '- action_required = "proceed" nếu điểm trung bình >= 8.0\n'
        '- action_required = "force_web_search" nếu điểm trung bình < 8.0'
    )

    # ── Tier 3: Memory Consolidation (MemoryConsolidator) ────────────────────

    CONSOLIDATION_SYSTEM: str = (
        "Bạn là bộ lọc trí nhớ thông minh. Từ đoạn hội thoại được cung cấp, "
        "hãy trích xuất CHÍNH XÁC các thông tin học thuật quan trọng mà người dùng cần nhớ:\n"
        "1. Khái niệm và định nghĩa đã được giải thích\n"
        "2. Kết quả nghiên cứu được đề cập\n"
        "3. Câu hỏi hoặc chủ đề người dùng đang nghiên cứu\n"
        "4. Tài liệu hoặc nguồn được tham chiếu\n\n"
        "Trả về danh sách bullet points NGẮN GỌN (mỗi điểm tối đa 20 từ). "
        "Bỏ qua chitchat và câu hỏi không có giá trị học thuật. "
        "Nếu không có nội dung đáng nhớ, trả về: (không có nội dung đáng nhớ)"
    )

    # ── Tier 4: Document Processing (Parser) ─────────────────────────────────

    PPTX_CLEANUP_SYSTEM: str = (
        "Bạn nhận được văn bản thô từ một slide PowerPoint. "
        "Nhiệm vụ: Làm sạch, cấu trúc hóa và đảm bảo nội dung mạch lạc. "
        "Giữ nguyên thuật ngữ kỹ thuật và số liệu. "
        "Bỏ các ký tự thừa, bullet points không có nghĩa, và lặp từ. "
        "Trả về nội dung đã làm sạch, không có giải thích thêm."
    )

    # ── Tier 5: Export (DocxExporter) ─────────────────────────────────────────

    DOCX_REPORT_SYSTEM: str = (
        "Bạn là trợ lý viết báo cáo học thuật chuyên nghiệp. "
        "Dựa vào nội dung hội thoại và tài liệu tham khảo được cung cấp, "
        "hãy tổng hợp thành một báo cáo có cấu trúc rõ ràng với:\n"
        "1. Tóm tắt điểm chính\n"
        "2. Nội dung chi tiết có section headers\n"
        "3. Kết luận\n"
        "Viết bằng tiếng Việt học thuật, súc tích và chính xác."
    )

    # ─── Build Methods ─────────────────────────────────────────────────────────

    @classmethod
    def build_answer(
        cls,
        ctx: PromptContext,
        fast: bool = False,
    ) -> tuple[str, str]:
        """
        Build (system_prompt, user_prompt) cho bước Generate Answer.

        Args:
            ctx : PromptContext với query, rag_context, web_context, conversation_history
            fast: True = dùng FAST_SYSTEM (daily_task), False = RESEARCH_SYSTEM (research_query)

        Returns:
            Tuple (system_prompt, user_prompt) để truyền vào WorkerEngine.generate()
        """
        system = cls.FAST_SYSTEM if fast else cls.RESEARCH_SYSTEM

        # Build user prompt với sections theo thứ tự ưu tiên
        parts: list[str] = []

        if ctx.conversation_history:
            parts.append(f"LỊCH SỬ HỘI THOẠI:\n{ctx.conversation_history}")

        if ctx.rag_context:
            parts.append(f"TÀI LIỆU NỘI BỘ:\n{ctx.rag_context}")

        if ctx.web_context:
            parts.append(f"KẾT QUẢ TÌM KIẾM WEB:\n{ctx.web_context}")

        if not ctx.rag_context and not ctx.web_context:
            parts.append("(Không tìm thấy ngữ cảnh. Trả lời dựa trên kiến thức chung.)")

        instruction = "Trả lời ngắn gọn bằng tiếng Việt:" if fast else "Trả lời bằng tiếng Việt học thuật:"
        parts.append(f"CÂU HỎI:\n{ctx.user_query}\n\n{instruction}")

        user_prompt = "\n\n---\n\n".join(parts)
        return system, user_prompt

    @classmethod
    def build_critique(
        cls,
        question: str,
        context_text: str,
    ) -> tuple[str, str]:
        """
        Build (system_prompt, user_prompt) cho bước Self-Critique.

        Args:
            question    : Câu hỏi gốc của người dùng
            context_text: Nội dung chunks đã được format thành chuỗi

        Returns:
            Tuple (system_prompt, user_prompt)
        """
        user_prompt = (
            f"CÂU HỎI:\n{question}\n\n"
            f"NGỮ CẢNH RAG TÌM ĐƯỢC:\n{context_text}\n\n"
            "Đánh giá chất lượng ngữ cảnh:"
        )
        return cls.CRITIQUE_SYSTEM, user_prompt

    @classmethod
    def build_consolidation(
        cls,
        conversation_text: str,
    ) -> tuple[str, str]:
        """
        Build (system_prompt, user_prompt) cho bước Memory Consolidation.

        Args:
            conversation_text: Nội dung hội thoại cần tóm tắt

        Returns:
            Tuple (system_prompt, user_prompt)
        """
        return cls.CONSOLIDATION_SYSTEM, conversation_text

    @classmethod
    def build_pptx_cleanup(
        cls,
        raw_slide_text: str,
    ) -> tuple[str, str]:
        """
        Build (system_prompt, user_prompt) để làm sạch nội dung PPTX slide.

        Args:
            raw_slide_text: Text thô từ slide PowerPoint

        Returns:
            Tuple (system_prompt, user_prompt)
        """
        return cls.PPTX_CLEANUP_SYSTEM, raw_slide_text

    @classmethod
    def build_docx_report(
        cls,
        conversation_summary: str,
        sources: Optional[list] = None,
    ) -> tuple[str, str]:
        """
        Build (system_prompt, user_prompt) để tạo báo cáo DOCX.

        Args:
            conversation_summary: Tóm tắt nội dung hội thoại
            sources             : Danh sách tên file tài liệu nguồn

        Returns:
            Tuple (system_prompt, user_prompt)
        """
        user_parts = [conversation_summary]
        if sources:
            sources_text = "\n".join(f"- {s}" for s in sources)
            user_parts.append(f"TÀI LIỆU THAM KHẢO:\n{sources_text}")
        return cls.DOCX_REPORT_SYSTEM, "\n\n".join(user_parts)

    @classmethod
    def format_rag_context(cls, context_chunks: list[dict]) -> str:
        """
        Chuẩn hóa format RAG chunks thành chuỗi text cho prompt.
        Tập trung formatting logic tại đây thay vì rải rác trong orchestrator.

        Args:
            context_chunks: List chunks từ HybridRAG.retrieve_context()

        Returns:
            Chuỗi text đã được format
        """
        if not context_chunks:
            return ""
        return "\n\n".join(
            f"[Tài liệu {i+1} | {c.get('source', 'unknown')} trang {c.get('page', 0)}]\n{c.get('text', '')}"
            for i, c in enumerate(context_chunks)
        )

    @classmethod
    def format_web_context(cls, web_results: list[str], max_results: int = 5) -> str:
        """
        Format web search results thành chuỗi text cho prompt.

        Args:
            web_results: List string kết quả web
            max_results: Giới hạn số kết quả (tránh vượt token limit)

        Returns:
            Chuỗi text đã được format
        """
        if not web_results:
            return ""
        capped = web_results[-max_results:]  # Lấy kết quả mới nhất
        return "\n\n".join(
            f"[Kết quả web {i+1}]\n{w}"
            for i, w in enumerate(capped)
        )
