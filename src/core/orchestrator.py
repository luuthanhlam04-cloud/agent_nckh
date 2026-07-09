"""
orchestrator.py - Bộ não điều phối chính (Core Orchestrator)
=============================================================
Kiến trúc 3 tầng (last agent.md Phần 2.3):

  WorkerEngine      : Động cơ suy luận chính - gọi OpenRouter qua OpenAI SDK.
                      Hỗ trợ streaming và non-streaming.

  SelfCritiqueAgent : LLM-as-a-judge chấm điểm ngữ cảnh RAG (Bước 6.1).
                      Nếu điểm < 8/10 -> kích hoạt web search.
                      API Contract 8.2 (last agent.md Phần 8).

  ReActOrchestrator : Máy trạng thái (State Machine) điều phối toàn bộ luồng.
                      Tương đương LangGraph StateGraph nhưng không phụ thuộc thư viện,
                      dễ migrate sang LangGraph bằng cách thay _run_graph() sau này.
                      Giới hạn web search: max_iterations=3 (Bước 6.2).

Luồng ReAct (Bước 6.1 -> 6.2):
  RAG_RETRIEVE -> CRITIQUE -> (score >= 8) GENERATE_ANSWER
                           -> (score < 8)  WEB_SEARCH -> CRITIQUE -> ... (max 3 vòng)
"""

import os
import re
import json
import logging
import gc
from typing import Optional, List, Dict, Any, TypedDict, Literal

import google.genai as genai
from google.genai import types as genai_types
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Web search
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    logging.warning("[Orchestrator] duckduckgo-search chưa cài. Web search sẽ bị skip.")

# ─── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger("Orchestrator")

# ─── Config ───────────────────────────────────────────────────────────────────
load_dotenv()
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

CRITIQUE_MODEL    = "gemini-2.0-flash"              # Model nhe, re cho self-critique
WORKER_MODEL      = "google/gemini-2.5-pro"          # Model manh qua OpenRouter
OPENROUTER_BASE   = "https://openrouter.ai/api/v1"
MAX_SEARCH_ITER   = 3                                # Gioi han vong lap DuckDuckGo
CRITIQUE_THRESHOLD = 8.0                             # Nguong diem chap nhan (8/10)
WEB_SEARCH_MAX_RESULTS = 5                           # So ket qua tim kiem toi da
MAX_WEB_IN_PROMPT = 5                                # [I4] Gioi han web results nho vao prompt


# ══════════════════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS - API Contract 8.2 (last agent.md Phần 8)
# ══════════════════════════════════════════════════════════════════════════════

class SelfCritiqueResult(BaseModel):
    """
    Kết quả chấm điểm chất lượng ngữ cảnh RAG bởi SelfCritiqueAgent.
    Ánh xạ trực tiếp từ API Contract 8.2 trong last agent.md.
    """
    relevance_score: float = Field(
        ..., ge=0.0, le=10.0,
        description="Điểm tương quan ngữ nghĩa của context với câu hỏi (0.0 - 10.0)"
    )
    answerability_score: float = Field(
        ..., ge=0.0, le=10.0,
        description="Điểm mức độ tự tin có thể trả lời đầy đủ (0.0 - 10.0)"
    )
    missing_information: str = Field(
        "",
        description="Mô tả phần tri thức còn thiếu (nếu có)"
    )
    action_required: Literal["proceed", "force_web_search"] = Field(
        ...,
        description="proceed nếu đủ tốt, force_web_search nếu cần tra mạng"
    )

    @property
    def avg_score(self) -> float:
        """Điểm trung bình tổng hợp."""
        return (self.relevance_score + self.answerability_score) / 2


# ══════════════════════════════════════════════════════════════════════════════
#  AgentState - TypedDict định nghĩa trạng thái của State Machine
#  (Tương thích 100% với LangGraph StateGraph khi nâng cấp sau)
# ══════════════════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    """
    Toàn bộ trạng thái của agent trong một vòng xử lý (một câu hỏi).
    Mỗi node trong state machine nhận AgentState và trả về AgentState đã cập nhật.
    """
    user_input: str                      # Câu hỏi gốc của người dùng
    context_chunks: List[Dict]           # Chunks ngữ cảnh từ HybridRAG
    web_results: List[str]               # Kết quả tìm kiếm DuckDuckGo
    critique: Optional[SelfCritiqueResult]  # Kết quả chấm điểm
    final_answer: str                    # Câu trả lời cuối cùng
    search_iterations: int               # Đếm số vòng lặp web search (max 3)
    error: Optional[str]                 # Lỗi nếu có


# ══════════════════════════════════════════════════════════════════════════════
#  WorkerEngine - Động cơ suy luận chính (OpenRouter)
# ══════════════════════════════════════════════════════════════════════════════

class WorkerEngine:
    """
    Gọi các LLM mạnh (Gemini Pro, Claude Sonnet...) qua cổng OpenRouter.

    Spec (last agent.md Phần 2.3):
      "Sử dụng chuẩn kết nối của thư viện openai trỏ endpoint về OpenRouter API.
       Cấu hình linh hoạt gọi các mô hình thương mại để xử lý lượng token khổng lồ
       từ GraphRAG mà không bị nghẽn cổ chai."

    Ưu điểm OpenRouter:
      - Băng thông thương mại -> triệt tiêu lỗi 429/503.
      - Đổi model chỉ cần đổi biến WORKER_MODEL (không sửa code).
    """

    def __init__(self, model: str = WORKER_MODEL):
        self.model = model
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        """Lazy-init OpenAI client trỏ về OpenRouter endpoint."""
        if self._client is None:
            if not OPENROUTER_API_KEY or "điền" in OPENROUTER_API_KEY.lower():
                raise ValueError(
                    "[WorkerEngine] OPENROUTER_API_KEY chưa được điền vào .env!"
                )
            self._client = OpenAI(
                base_url=OPENROUTER_BASE,
                api_key=OPENROUTER_API_KEY,
            )
            logger.info(f"[WorkerEngine] OpenRouter client sẵn sàng. Model: {self.model}")
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Sinh câu trả lời từ LLM thông qua OpenRouter.

        Args:
            system_prompt: Hướng dẫn hành vi cho model.
            user_prompt  : Câu hỏi + ngữ cảnh RAG được nhồi vào.
            temperature  : Độ sáng tạo (0.7 cho câu trả lời học thuật).
            max_tokens   : Giới hạn độ dài output.

        Returns:
            Chuỗi văn bản trả lời của LLM.
        """
        client = self._get_client()
        logger.info(f"[WorkerEngine] Gọi {self.model} qua OpenRouter...")

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            answer = response.choices[0].message.content or ""
            logger.info(f"[WorkerEngine] Nhận phản hồi: {len(answer)} ký tự.")
            return answer

        except Exception as e:
            # Bắt lỗi Safety Filter của Google (FinishReason.SAFETY - Bước 7.2 spec)
            error_msg = str(e)
            if "safety" in error_msg.lower() or "SAFETY" in error_msg:
                logger.warning("[WorkerEngine] Kích hoạt bộ lọc an toàn Google. Trả thông báo.")
                return (
                    "Tài liệu nghiên cứu chuyên ngành chứa thuật ngữ nhạy cảm "
                    "bị bộ lọc an toàn từ chối xử lý. Vui lòng thử diễn đạt lại câu hỏi."
                )
            logger.error(f"[WorkerEngine] Lỗi gọi API: {e}")
            return f"Hệ thống lõi gặp sự cố kết nối API: {str(e)[:100]}. Vui lòng thử lại sau."

    def close(self):
        """Giải phóng client sau khi dùng."""
        if self._client:
            self._client = None
            gc.collect()


# ══════════════════════════════════════════════════════════════════════════════
#  SelfCritiqueAgent - LLM-as-a-Judge chấm điểm ngữ cảnh RAG
# ══════════════════════════════════════════════════════════════════════════════

_CRITIQUE_SYSTEM_PROMPT = """Bạn là bộ chấm điểm chất lượng ngữ cảnh (Self-Critique Agent).
Nhiệm vụ: Đánh giá mức độ phù hợp của NGỮCẢNH RAG với CÂU HỎI người dùng.
Trả về JSON theo cấu trúc sau, KHÔNG thêm giải thích, KHÔNG dùng markdown:
{
  "relevance_score": <số thực 0.0-10.0>,
  "answerability_score": <số thực 0.0-10.0>,
  "missing_information": "<mô tả ngắn gọn phần còn thiếu hoặc empty string>",
  "action_required": "proceed" | "force_web_search"
}
Quy tắc:
- action_required = "proceed" nếu điểm trung bình >= 8.0
- action_required = "force_web_search" nếu điểm trung bình < 8.0"""


class SelfCritiqueAgent:
    """
    Chấm điểm chất lượng ngữ cảnh RAG bằng Gemini Flash (LLM-as-a-judge).

    Spec Bước 6.1:
      "Một modul AI siêu nhẹ quét đống context, đối chiếu câu hỏi gốc,
       chấm điểm theo cấu trúc JSON Contract của Self-Critique Agent."
    """

    def __init__(self):
        self._model = None

    def _get_model(self):
        if self._model is None:
            if not GEMINI_API_KEY or "điền" in GEMINI_API_KEY.lower():
                raise ValueError("[SelfCritiqueAgent] Cần GEMINI_API_KEY trong .env!")
            self._model = genai.Client(api_key=GEMINI_API_KEY)
        return self._model

    def evaluate(
        self,
        question: str,
        context_chunks: List[Dict],
    ) -> SelfCritiqueResult:
        """
        Chấm điểm ngữ cảnh RAG so với câu hỏi.

        Args:
            question      : Câu hỏi gốc của người dùng.
            context_chunks: Danh sách chunk từ HybridRAG.retrieve_context().

        Returns:
            SelfCritiqueResult với điểm và quyết định hành động.
        """
        if not context_chunks:
            logger.warning("[SelfCritiqueAgent] Context rỗng -> force_web_search.")
            return SelfCritiqueResult(
                relevance_score=0.0,
                answerability_score=0.0,
                missing_information="Không có ngữ cảnh nào từ kho dữ liệu nội bộ.",
                action_required="force_web_search",
            )

        # Ghép nội dung chunks thành chuỗi để chấm điểm
        context_text = "\n\n".join(
            f"[Chunk {i+1}] {c.get('text', '')[:500]}"
            for i, c in enumerate(context_chunks[:5])  # Chỉ dùng top-5 để tiết kiệm token
        )

        prompt = f"""CÂU HỎI:
{question}

NGỮ CẢNH RAG TÌM ĐƯỢC:
{context_text}

Đánh giá chất lượng ngữ cảnh:"""

        try:
            # [C2 FIX] Truyen dung system_prompt cho SelfCritiqueAgent
            # Phien ban cu chi truyen user prompt -> model khong co huong dan cham diem
            response = self._get_model().models.generate_content(
                model=CRITIQUE_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_CRITIQUE_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.0,
                    max_output_tokens=256,
                ),
            )
            raw = re.sub(r"```(?:json)?\s*|\s*```", "", response.text.strip())
            data = json.loads(raw)
            result = SelfCritiqueResult.model_validate(data)
            logger.info(
                f"[SelfCritiqueAgent] Score: relevance={result.relevance_score} | "
                f"answerability={result.answerability_score} | avg={result.avg_score:.1f} | "
                f"action={result.action_required}"
            )
            return result

        except Exception as e:
            logger.error(f"[SelfCritiqueAgent] Lỗi chấm điểm: {e}. Fallback proceed.")
            return SelfCritiqueResult(
                relevance_score=7.0,
                answerability_score=7.0,
                missing_information="",
                action_required="proceed",
            )


# ══════════════════════════════════════════════════════════════════════════════
#  ReActOrchestrator - Máy trạng thái ReAct (State Machine)
# ══════════════════════════════════════════════════════════════════════════════

# System prompt cho WorkerEngine sinh câu trả lời học thuật
_ANSWER_SYSTEM_PROMPT = """Bạn là Digital Scholar - trợ lý nghiên cứu học thuật chuyên nghiệp.
Nhiệm vụ: Dựa vào NGỮ CẢNH được cung cấp, trả lời câu hỏi bằng tiếng Việt học thuật mượt mà.
Quy tắc:
- Ưu tiên thông tin từ ngữ cảnh. Nếu ngữ cảnh thiếu, dùng kiến thức chung có ghi chú.
- Sử dụng thuật ngữ học thuật chính xác.
- Trình bày rõ ràng, mạch lạc. Không trả lời mơ hồ.
- KHÔNG bịa đặt số liệu hay trích dẫn không có trong ngữ cảnh."""


class ReActOrchestrator:
    """
    Máy trạng thái điều phối toàn bộ luồng suy luận ReAct của Digital Scholar.

    Sơ đồ trạng thái (Bước 6.1 - 6.2 trong last agent.md):

    ┌─────────────────────────────────────────────────────────────────┐
    │  [START]                                                         │
    │      ↓                                                           │
    │  [RETRIEVE]  HybridRAG.retrieve_context() -> context_chunks     │
    │      ↓                                                           │
    │  [CRITIQUE]  SelfCritiqueAgent.evaluate() -> score + action     │
    │      ↓                                                           │
    │  score >= 8? ──YES──> [GENERATE] WorkerEngine -> final_answer   │
    │      │                                                           │
    │     NO                                                           │
    │      ↓                                                           │
    │  [WEB_SEARCH] DuckDuckGo -> web_results (max_iterations=3)      │
    │      ↓                                                           │
    │  Merge web + local context -> [CRITIQUE] lại                    │
    │      ↓                                                           │
    │  (sau 3 vòng vẫn thất bại) -> [GENERATE] với best effort        │
    │      ↓                                                           │
    │  [END]                                                           │
    └─────────────────────────────────────────────────────────────────┘

    Thiết kế để migrate LangGraph: mỗi node là method độc lập,
    nhận AgentState và trả về AgentState. Thêm StateGraph wrapper là xong.
    """

    def __init__(
        self,
        hybrid_rag=None,
        worker_model: str = WORKER_MODEL,
    ):
        """
        Args:
            hybrid_rag  : Instance HybridRAG từ Giai đoạn 2 (dependency injection).
            worker_model: Tên model trên OpenRouter (có thể đổi linh hoạt).
        """
        self._rag = hybrid_rag
        self._worker = WorkerEngine(model=worker_model)
        self._critique = SelfCritiqueAgent()
        self._last_sources: list = []   # Giai doan 5: theo doi nguon de DocxExporter

    def set_rag(self, hybrid_rag):
        """Inject HybridRAG sau khi khởi tạo (tránh circular dependency)."""
        self._rag = hybrid_rag

    # ── Node 1: Truy xuất ngữ cảnh từ HybridRAG ──────────────────────────────
    def _node_retrieve(self, state: AgentState) -> AgentState:
        """
        Bước 5.1 -> 5.3: Truy xuất ngữ cảnh lai kép (Vector + Graph).

        [C1-FIX] Đã sửa: dead code (try/except sau return) đã được xóa và
        bọc đúng vị trí quanh lệnh gọi retrieve_context() thực sự.
        [M1-FIX] Đã xóa _wide_retrieval dead key — top_k cố định = 5.
        """
        if self._rag is None:
            logger.warning("[ReAct:RETRIEVE] HybridRAG chưa được inject. Context rỗng.")
            return {**state, "context_chunks": []}

        try:
            context_chunks = self._rag.retrieve_context(
                query=state["user_input"],
                top_k=5,
            )
            # Lưu nguồn để get_last_sources() trả về cho DocxExporter (Giai đoạn 5)
            self._last_sources = list({
                c.get("source", "") for c in context_chunks if c.get("source")
            })
            logger.info(
                "[ReAct:RETRIEVE] Thu được %d chunks từ %d nguồn.",
                len(context_chunks), len(self._last_sources)
            )
            return {**state, "context_chunks": context_chunks}
        except Exception as e:
            logger.error("[ReAct:RETRIEVE] Lỗi truy xuất RAG: %s", e)
            return {**state, "context_chunks": [], "error": str(e)}

    # ── Node 2: Chấm điểm ngữ cảnh (Self-Critique) ───────────────────────────
    def _node_critique(self, state: AgentState) -> AgentState:
        """
        Bước 6.1: Chấm điểm chất lượng ngữ cảnh RAG.
        """
        try:
            critique = self._critique.evaluate(
                question=state["user_input"],
                context_chunks=state["context_chunks"],
            )
            return {**state, "critique": critique}
        except Exception as e:
            logger.error(f"[ReAct:CRITIQUE] Lỗi: {e}. Fallback proceed.")
            return {
                **state,
                "critique": SelfCritiqueResult(
                    relevance_score=7.0, answerability_score=7.0,
                    missing_information="", action_required="proceed"
                )
            }

    # ── Node 3: Tìm kiếm web (DuckDuckGo) ────────────────────────────────────
    def _node_web_search(self, state: AgentState) -> AgentState:
        """
        Bước 6.2: Kích hoạt DuckDuckGo khi ngữ cảnh local không đủ.
        Giới hạn max_iterations=3 bằng cầu dao an toàn cứng.
        """
        current_iter = state.get("search_iterations", 0)

        # Cầu dao an toàn cứng - tránh vòng lặp vô tận
        if current_iter >= MAX_SEARCH_ITER:
            logger.warning(
                f"[ReAct:WEB_SEARCH] Đã đạt giới hạn {MAX_SEARCH_ITER} vòng tìm kiếm. "
                "Dừng và dùng best effort."
            )
            return {**state, "search_iterations": current_iter}

        if not DDGS_AVAILABLE:
            logger.warning("[ReAct:WEB_SEARCH] duckduckgo-search chưa cài. Bỏ qua.")
            return {**state, "search_iterations": current_iter + 1}

        logger.info(
            f"[ReAct:WEB_SEARCH] Vòng {current_iter + 1}/{MAX_SEARCH_ITER}: "
            f"Tìm kiếm '{state['user_input'][:50]}...'"
        )

        try:
            web_texts = []
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    keywords=state["user_input"],
                    max_results=WEB_SEARCH_MAX_RESULTS,
                ))
                for r in results:
                    snippet = f"[{r.get('title', '')}]\n{r.get('body', '')}"
                    web_texts.append(snippet)

            logger.info(f"[ReAct:WEB_SEARCH] Tìm được {len(web_texts)} kết quả.")

            # Merge kết quả web vào web_results (thêm vào, không ghi đè)
            existing = state.get("web_results", [])
            return {
                **state,
                "web_results": existing + web_texts,
                "search_iterations": current_iter + 1,
            }

        except Exception as e:
            logger.error(f"[ReAct:WEB_SEARCH] Lỗi DuckDuckGo: {e}")
            return {**state, "search_iterations": current_iter + 1}

    # ── Node 4: Sinh câu trả lời cuối cùng ───────────────────────────────────
    def _node_generate(self, state: AgentState) -> AgentState:
        """
        Bước 5.3: Nhồi ngữ cảnh vào prompt và gọi WorkerEngine sinh câu trả lời.
        """
        # [I4 FIX] Gioi han web_results truoc khi nho vao prompt
        # Sau 3 vong × 5 ket qua = 15 web results co the vuot token limit 32K
        all_web = state.get("web_results", [])
        web_results_capped = all_web[-MAX_WEB_IN_PROMPT:]  # Lay 5 ket qua moi nhat
        if len(all_web) > MAX_WEB_IN_PROMPT:
            logger.info(
                "[ReAct:GENERATE] Cap web results: %d -> %d de tranh vuot token limit.",
                len(all_web), MAX_WEB_IN_PROMPT,
            )

        rag_text = "\n\n".join(
            f"[Tai lieu {i+1} | {c.get('source', 'unknown')} trang {c.get('page', 0)}]\n{c.get('text', '')}"
            for i, c in enumerate(state.get("context_chunks", []))
        )
        web_text = "\n\n".join(
            f"[Ket qua web {i+1}]\n{w}"
            for i, w in enumerate(web_results_capped)
        )

        context_combined = ""
        if rag_text:
            context_combined += f"=== Tài liệu nội bộ ===\n{rag_text}\n\n"
        if web_text:
            context_combined += f"=== Kết quả tìm kiếm web ===\n{web_text}\n\n"

        if not context_combined:
            context_combined = "(Không tìm thấy ngữ cảnh. Trả lời dựa trên kiến thức chung.)"

        user_prompt = f"""NGỮ CẢNH:
{context_combined}

CÂU HỎI:
{state['user_input']}

Trả lời bằng tiếng Việt học thuật:"""

        try:
            answer = self._worker.generate(
                system_prompt=_ANSWER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
            return {**state, "final_answer": answer}
        except Exception as e:
            logger.error(f"[ReAct:GENERATE] Lỗi WorkerEngine: {e}")
            return {
                **state,
                "final_answer": f"Xin lỗi, hệ thống gặp sự cố khi xử lý câu hỏi. Lỗi: {str(e)[:100]}",
                "error": str(e),
            }

    # ── Điều kiện chuyển trạng thái ──────────────────────────────────────────
    def _should_search(self, state: AgentState) -> bool:
        """Bước 6.2: Quyết định có cần web search không."""
        critique = state.get("critique")
        if critique is None:
            return False
        if state.get("search_iterations", 0) >= MAX_SEARCH_ITER:
            return False  # Đã đạt giới hạn, bắt buộc generate
        return critique.action_required == "force_web_search"

    # ── Entry point chính ─────────────────────────────────────────────────────
    def run(
        self,
        user_input: str,
        additional_context: Optional[List[Dict]] = None,
    ) -> str:
        """
        Chạy toàn bộ luồng ReAct cho một câu hỏi của người dùng.

        Args:
            user_input         : Câu hỏi của người dùng.
            additional_context : Context bổ sung (ví dụ: kết quả từ Regex interceptor).

        Returns:
            Chuỗi câu trả lời cuối cùng bằng tiếng Việt.
        """
        # Khởi tạo trạng thái ban đầu
        state: AgentState = {
            "user_input": user_input,
            "context_chunks": additional_context or [],
            "web_results": [],
            "critique": None,
            "final_answer": "",
            "search_iterations": 0,
            "error": None,
        }

        # [S5-FIX] Chỉ thêm "..." khi input thực sự bị cắt
        preview = user_input[:60] + ("..." if len(user_input) > 60 else "")
        logger.info("[ReActOrchestrator] === Bắt đầu xử lý: '%s' ===", preview)

        # ── Bước 1: Truy xuất ngữ cảnh ──────────────────────────────────────
        state = self._node_retrieve(state)

        # ── Bước 2: Critique + ReAct loop ────────────────────────────────────
        state = self._node_critique(state)

        while self._should_search(state):
            # Track so ket qua web truoc khi search de chi lay ket qua MOI
            prev_web_count = len(state.get("web_results", []))

            # Web search de bo sung ngu canh con thieu
            state = self._node_web_search(state)

            # [BUG-9 FIX] Chi convert KET QUA WEB MOI (tu vong nay) thanh chunks,
            # khong convert lai tat ca web_results cu -> tranh duplicate trong context_chunks.
            all_web = state.get("web_results", [])
            new_web_texts = all_web[prev_web_count:]   # Chi lay phan moi them vao
            new_web_chunks = [
                {"text": w, "source": "web_search", "page": 0, "score": 0.7}
                for w in new_web_texts
            ]
            state = {**state, "context_chunks": state["context_chunks"] + new_web_chunks}

            # Critique lai voi context moi
            state = self._node_critique(state)

        # ── Bước 3: Sinh câu trả lời ─────────────────────────────────────────
        state = self._node_generate(state)

        logger.info(
            f"[ReActOrchestrator] === Hoàn thành. "
            f"Search loops={state['search_iterations']} | "
            f"Answer length={len(state['final_answer'])} chars ==="
        )
        return state["final_answer"]

    def get_last_sources(self) -> list:
        """
        [Giai doan 5] Tra ve danh sach nguon (ten file) tu lan RAG gan nhat.
        Duoc dung boi DocxExporter de xay dung phan Tai Lieu Tham Khao.
        """
        return list(self._last_sources)

    def close(self):
        """Dọn dẹp tài nguyên."""
        self._worker.close()
        gc.collect()
        logger.info("[ReActOrchestrator] Đã dọn sạch tài nguyên.")


# ─── Test nhanh khi chạy trực tiếp ───────────────────────────────────────────
if __name__ == "__main__":
    print("--- Orchestrator Component Test ---")
    print("Testing SelfCritiqueResult Pydantic model...\n")

    # Test Pydantic model (không cần API key)
    test_data = {
        "relevance_score": 9.2,
        "answerability_score": 8.5,
        "missing_information": "Missing chart data from paper section 3",
        "action_required": "proceed",
    }
    result = SelfCritiqueResult.model_validate(test_data)
    assert result.avg_score == (9.2 + 8.5) / 2
    print(f"SelfCritiqueResult: avg_score={result.avg_score:.2f} | action={result.action_required}")
    print("Pydantic model test PASSED!")

    # Test AgentState TypedDict structure
    state: AgentState = {
        "user_input": "GraphRAG la gi?",
        "context_chunks": [],
        "web_results": [],
        "critique": None,
        "final_answer": "",
        "search_iterations": 0,
        "error": None,
    }
    print(f"\nAgentState initialized: {list(state.keys())}")
    print("AgentState structure test PASSED!")

    print("\nAll Orchestrator tests passed!")
    print("NOTE: Full ReAct loop requires OPENROUTER_API_KEY and GEMINI_API_KEY in .env")
