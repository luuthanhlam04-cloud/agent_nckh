"""
orchestrator.py - Bá»™ nÃ£o Ä‘iá» u phá»‘i chÃ­nh (Core Orchestrator)
=============================================================
Kiáº¿n trÃºc 3 táº§ng (last agent.md Pháº§n 2.3):

  WorkerEngine      : Ä á»™ng cÆ¡ suy luáº­n chÃ­nh - gá» i OpenRouter qua OpenAI SDK.
                      Há»— trá»£ streaming vÃ  non-streaming.

  SelfCritiqueAgent : LLM-as-a-judge cháº¥m Ä‘iá»ƒm ngá»¯ cáº£nh RAG (BÆ°á»›c 6.1).
                      Náº¿u Ä‘iá»ƒm < 8/10 -> kÃ­ch hoáº¡t web search.
                      API Contract 8.2 (last agent.md Pháº§n 8).

  ReActOrchestrator : MÃ¡y tráº¡ng thÃ¡i (State Machine) Ä‘iá» u phá»‘i toÃ n bá»™ luá»“ng.
                      TÆ°Æ¡ng Ä‘Æ°Æ¡ng LangGraph StateGraph nhÆ°ng khÃ´ng phá»¥ thuá»™c thÆ° viá»‡n,
                      dá»… migrate sang LangGraph báº±ng cÃ¡ch thay _run_graph() sau nÃ y.
                      Giá»›i háº¡n web search: max_iterations=3 (BÆ°á»›c 6.2).

Luá»“ng ReAct (BÆ°á»›c 6.1 -> 6.2):
  RAG_RETRIEVE -> CRITIQUE -> (score >= 8) GENERATE_ANSWER
                           -> (score < 8)  WEB_SEARCH -> CRITIQUE -> ... (max 3 vÃ²ng)
"""

import os
import re
import json
import logging
import gc
from typing import Optional, List, Dict, Any, TypedDict, Literal

import google.genai as genai
from src.shared.metrics import PipelineMetrics, timed
from google.genai import types as genai_types
from openai import OpenAI
from pydantic import BaseModel, Field

from src.core.interfaces import ILLMClient
from src.core.prompt_builder import PromptBuilder, PromptContext
from src.core.orchestrator_config import OrchestratorConfig, get_config_for_intent

# Web search
try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    logging.warning("[Orchestrator] ddgs chua cai. Web search se bi skip. Chay: pip install ddgs")

# â”€â”€â”€ Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
logger = logging.getLogger("Orchestrator")

# â”€â”€â”€ Config (Ä‘á»c tá»« env Ä‘Ã£ Ä‘Æ°á»£c load_dotenv() trong main.py) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from src.shared.config import GEMINI_API_KEY

CRITIQUE_MODEL    = "gemini-3.1-flash-lite"             # Benchmarked: nhanh nhat (0.72s), JSON mode, mien phi
WORKER_MODEL      = "google/gemini-2.5-pro"          # Model manh qua OpenRouter
OPENROUTER_BASE   = "https://openrouter.ai/api/v1"
MAX_SEARCH_ITER   = 3                                # Gioi han vong lap DuckDuckGo
CRITIQUE_THRESHOLD = 8.0                             # Nguong diem chap nhan (8/10)
WEB_SEARCH_MAX_RESULTS = 5                           # So ket qua tim kiem toi da
MAX_WEB_IN_PROMPT = 5                                # [I4] Gioi han web results nho vao prompt


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PYDANTIC MODELS - API Contract 8.2 (last agent.md Pháº§n 8)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class SelfCritiqueResult(BaseModel):
    """
    Káº¿t quáº£ cháº¥m Ä‘iá»ƒm cháº¥t lÆ°á»£ng ngá»¯ cáº£nh RAG bá»Ÿi SelfCritiqueAgent.
    Ãnh xáº¡ trá»±c tiáº¿p tá»« API Contract 8.2 trong last agent.md.
    """
    relevance_score: float = Field(
        ..., ge=0.0, le=10.0,
        description="Äiá»ƒm tÆ°Æ¡ng quan ngá»¯ nghÄ©a cá»§a context vá»›i cÃ¢u há»i (0.0 - 10.0)"
    )
    answerability_score: float = Field(
        ..., ge=0.0, le=10.0,
        description="Äiá»ƒm má»©c Ä‘á»™ tá»± tin cÃ³ thá»ƒ tráº£ lá»i Ä‘áº§y Ä‘á»§ (0.0 - 10.0)"
    )
    missing_information: str = Field(
        "",
        description="MÃ´ táº£ pháº§n tri thá»©c cÃ²n thiáº¿u (náº¿u cÃ³)"
    )
    action_required: Literal["proceed", "force_web_search"] = Field(
        ...,
        description="proceed náº¿u Ä‘á»§ tá»‘t, force_web_search náº¿u cáº§n tra máº¡ng"
    )

    @property
    def avg_score(self) -> float:
        """Äiá»ƒm trung bÃ¬nh tá»•ng há»£p."""
        return (self.relevance_score + self.answerability_score) / 2


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  AgentState - TypedDict Ä‘á»‹nh nghÄ©a tráº¡ng thÃ¡i cá»§a State Machine
#  (TÆ°Æ¡ng thÃ­ch 100% vá»›i LangGraph StateGraph khi nÃ¢ng cáº¥p sau)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class AgentState(TypedDict):
    """
    ToÃ n bá»™ tráº¡ng thÃ¡i cá»§a agent trong má»™t vÃ²ng xá»­ lÃ½ (má»™t cÃ¢u há»i).
    Má»—i node trong state machine nháº­n AgentState vÃ  tráº£ vá» AgentState Ä‘Ã£ cáº­p nháº­t.
    """
    user_input: str                      # CÃ¢u há»i gá»‘c cá»§a ngÆ°á»i dÃ¹ng
    context_chunks: List[Dict]           # Chunks ngá»¯ cáº£nh tá»« HybridRAG
    web_results: List[str]               # Káº¿t quáº£ tÃ¬m kiáº¿m DuckDuckGo
    critique: Optional[SelfCritiqueResult]  # Káº¿t quáº£ cháº¥m Ä‘iá»ƒm
    final_answer: str                    # CÃ¢u tráº£ lá»i cuá»‘i cÃ¹ng
    search_iterations: int               # Äáº¿m sá»‘ vÃ²ng láº·p web search (max 3)
    error: Optional[str]
    metrics: Any                 # Lá»—i náº¿u cÃ³


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  WorkerEngine - Äá»™ng cÆ¡ suy luáº­n chÃ­nh (OpenRouter)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class WorkerEngine(ILLMClient):
    """
    Gá»i cÃ¡c LLM máº¡nh (Gemini Pro, Claude Sonnet...) qua cá»•ng OpenRouter.

    Spec (last agent.md Pháº§n 2.3):
      "Sá»­ dá»¥ng chuáº©n káº¿t ná»‘i cá»§a thÆ° viá»‡n openai trá» endpoint vá» OpenRouter API.
       Cáº¥u hÃ¬nh linh hoáº¡t gá»i cÃ¡c mÃ´ hÃ¬nh thÆ°Æ¡ng máº¡i Ä‘á»ƒ xá»­ lÃ½ lÆ°á»£ng token khá»•ng lá»“
       tá»« GraphRAG mÃ  khÃ´ng bá»‹ ngháº½n cá»• chai."

    Æ¯u Ä‘iá»ƒm OpenRouter:
      - BÄƒng thÃ´ng thÆ°Æ¡ng máº¡i -> triá»‡t tiÃªu lá»—i 429/503.
      - Äá»•i model chá»‰ cáº§n Ä‘á»•i biáº¿n WORKER_MODEL (khÃ´ng sá»­a code).
    """

    def __init__(self, model: str = WORKER_MODEL):
        self.model = model
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        """Lazy-init OpenAI client trá» vá» OpenRouter endpoint."""
        if self._client is None:
            if not OPENROUTER_API_KEY or "Ä‘iá»n" in OPENROUTER_API_KEY.lower():
                raise ValueError(
                    "[WorkerEngine] OPENROUTER_API_KEY chÆ°a Ä‘Æ°á»£c Ä‘iá»n vÃ o .env!"
                )
            self._client = OpenAI(
                base_url=OPENROUTER_BASE,
                api_key=OPENROUTER_API_KEY,
            )
            logger.info(f"[WorkerEngine] OpenRouter client sáºµn sÃ ng. Model: {self.model}")
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Sinh cÃ¢u tráº£ lá»i tá»« LLM thÃ´ng qua OpenRouter.

        Args:
            system_prompt: HÆ°á»›ng dáº«n hÃ nh vi cho model.
            user_prompt  : CÃ¢u há»i + ngá»¯ cáº£nh RAG Ä‘Æ°á»£c nhá»“i vÃ o.
            temperature  : Äá»™ sÃ¡ng táº¡o (0.7 cho cÃ¢u tráº£ lá»i há»c thuáº­t).
            max_tokens   : Giá»›i háº¡n Ä‘á»™ dÃ i output.

        Returns:
            Chuá»—i vÄƒn báº£n tráº£ lá»i cá»§a LLM.
        """
        client = self._get_client()
        logger.info(f"[WorkerEngine] Gá»i {self.model} qua OpenRouter...")

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta

        except Exception as e:
            # [BUG-F FIX] DÃ¹ng yield thay vÃ¬ return trong generator function.
            # return <string> trong generator chá»‰ raise StopIteration, caller khÃ´ng nháº­n Ä‘Æ°á»£c message.
            error_msg = str(e)
            if "safety" in error_msg.lower() or "SAFETY" in error_msg:
                logger.warning("[WorkerEngine] KÃ­ch hoáº¡t bá»™ lá»c an toÃ n Google. Tráº£ thÃ´ng bÃ¡o.")
                yield (
                    "TÃ i liá»‡u nghiÃªn cá»©u chuyÃªn ngÃ nh chá»©a thuáº­t ngá»¯ nháº¡y cáº£m "
                    "bá»‹ bá»™ lá»c an toÃ n tá»« chá»‘i xá»­ lÃ½. Vui lÃ²ng thá»­ diá»…n Ä‘áº¡t láº¡i cÃ¢u há»i."
                )
                return
            logger.error("[WorkerEngine] Lá»—i gá»i API: %s", e, exc_info=True)
            yield f"Há»‡ thá»‘ng lÃµi gáº·p sá»± cá»‘ káº¿t ná»‘i API: {str(e)[:100]}. Vui lÃ²ng thá»­ láº¡i sau."

    def close(self):
        """Giáº£i phÃ³ng client sau khi dÃ¹ng."""
        if self._client:
            self._client = None
            gc.collect()


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  SelfCritiqueAgent - LLM-as-a-Judge cháº¥m Ä‘iá»ƒm ngá»¯ cáº£nh RAG
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

_CRITIQUE_SYSTEM_PROMPT = """Báº¡n lÃ  bá»™ cháº¥m Ä‘iá»ƒm cháº¥t lÆ°á»£ng ngá»¯ cáº£nh (Self-Critique Agent).
Nhiá»‡m vá»¥: ÄÃ¡nh giÃ¡ má»©c Ä‘á»™ phÃ¹ há»£p cá»§a NGá»®Cáº¢NH RAG vá»›i CÃ‚U Há»ŽI ngÆ°á»i dÃ¹ng.
Tráº£ vá» JSON theo cáº¥u trÃºc sau, KHÃ”NG thÃªm giáº£i thÃ­ch, KHÃ”NG dÃ¹ng markdown:
{
  "relevance_score": <sá»‘ thá»±c 0.0-10.0>,
  "answerability_score": <sá»‘ thá»±c 0.0-10.0>,
  "missing_information": "<mÃ´ táº£ ngáº¯n gá»n pháº§n cÃ²n thiáº¿u hoáº·c empty string>",
  "action_required": "proceed" | "force_web_search"
}
Quy táº¯c:
- action_required = "proceed" náº¿u Ä‘iá»ƒm trung bÃ¬nh >= 8.0
- action_required = "force_web_search" náº¿u Ä‘iá»ƒm trung bÃ¬nh < 8.0"""


class SelfCritiqueAgent:
    """
    Cháº¥m Ä‘iá»ƒm cháº¥t lÆ°á»£ng ngá»¯ cáº£nh RAG báº±ng Gemini Flash (LLM-as-a-judge).

    Spec BÆ°á»›c 6.1:
      "Má»™t modul AI siÃªu nháº¹ quÃ©t Ä‘á»‘ng context, Ä‘á»‘i chiáº¿u cÃ¢u há»i gá»‘c,
       cháº¥m Ä‘iá»ƒm theo cáº¥u trÃºc JSON Contract cá»§a Self-Critique Agent."
    """

    def __init__(self):
        self._model = None

    def _get_model(self):
        if self._model is None:
            if not GEMINI_API_KEY or "Ä‘iá»n" in GEMINI_API_KEY.lower():
                raise ValueError("[SelfCritiqueAgent] Cáº§n GEMINI_API_KEY trong .env!")
            self._model = genai.Client(api_key=GEMINI_API_KEY)
        return self._model

    def evaluate(
        self,
        question: str,
        context_chunks: List[Dict],
    ) -> SelfCritiqueResult:
        """
        Cháº¥m Ä‘iá»ƒm ngá»¯ cáº£nh RAG so vá»›i cÃ¢u há»i.

        Args:
            question      : CÃ¢u há»i gá»‘c cá»§a ngÆ°á»i dÃ¹ng.
            context_chunks: Danh sÃ¡ch chunk tá»« HybridRAG.retrieve_context().

        Returns:
            SelfCritiqueResult vá»›i Ä‘iá»ƒm vÃ  quyáº¿t Ä‘á»‹nh hÃ nh Ä‘á»™ng.
        """
        if not context_chunks:
            logger.warning("[SelfCritiqueAgent] Context rá»—ng -> force_web_search.")
            return SelfCritiqueResult(
                relevance_score=0.0,
                answerability_score=0.0,
                missing_information="KhÃ´ng cÃ³ ngá»¯ cáº£nh nÃ o tá»« kho dá»¯ liá»‡u ná»™i bá»™.",
                action_required="force_web_search",
            )

        # GhÃ©p ná»™i dung chunks thÃ nh chuá»—i Ä‘á»ƒ cháº¥m Ä‘iá»ƒm
        context_text = "\n\n".join(
            f"[Chunk {i+1}] {c.get('text', '')[:500]}"
            for i, c in enumerate(context_chunks[:5])  # Chá»‰ dÃ¹ng top-5 Ä‘á»ƒ tiáº¿t kiá»‡m token
        )

        prompt = f"""CÃ‚U Há»ŽI:
{question}

NGá»® Cáº¢NH RAG TÃŒM Ä Æ¯á»¢C:
{context_text}

Ä Ã¡nh giÃ¡ cháº¥t lÆ°á»£ng ngá»¯ cáº£nh:"""

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
            logger.error(f"[SelfCritiqueAgent] Lá»—i cháº¥m Ä‘iá»ƒm: {e}. Fallback proceed.")
            return SelfCritiqueResult(
                relevance_score=7.0,
                answerability_score=7.0,
                missing_information="",
                action_required="proceed",
            )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  ReActOrchestrator - MÃ¡y tráº¡ng thÃ¡i ReAct (State Machine)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

# Các prompt đã chuyển sang PromptBuilder


class ReActOrchestrator:
    """
    MÃ¡y tráº¡ng thÃ¡i Ä‘iá»u phá»‘i toÃ n bá»™ luá»“ng suy luáº­n ReAct cá»§a Digital Scholar.

    SÆ¡ Ä‘á»“ tráº¡ng thÃ¡i (BÆ°á»›c 6.1 - 6.2 trong last agent.md):

    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
    â”‚  [START]                                                         â”‚
    â”‚      â†“                                                           â”‚
    â”‚  [RETRIEVE]  HybridRAG.retrieve_context() -> context_chunks     â”‚
    â”‚      â†“                                                           â”‚
    â”‚  [CRITIQUE]  SelfCritiqueAgent.evaluate() -> score + action     â”‚
    â”‚      â†“                                                           â”‚
    â”‚  score >= 8? â”€â”€YESâ”€â”€> [GENERATE] WorkerEngine -> final_answer   â”‚
    â”‚      â”‚                                                           â”‚
    â”‚     NO                                                           â”‚
    â”‚      â†“                                                           â”‚
    â”‚  [WEB_SEARCH] DuckDuckGo -> web_results (max_iterations=3)      â”‚
    â”‚      â†“                                                           â”‚
    â”‚  Merge web + local context -> [CRITIQUE] láº¡i                    â”‚
    â”‚      â†“                                                           â”‚
    â”‚  (sau 3 vÃ²ng váº«n tháº¥t báº¡i) -> [GENERATE] vá»›i best effort        â”‚
    â”‚      â†“                                                           â”‚
    â”‚  [END]                                                           â”‚
    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜

    Thiáº¿t káº¿ Ä‘á»ƒ migrate LangGraph: má»—i node lÃ  method Ä‘á»™c láº­p,
    nháº­n AgentState vÃ  tráº£ vá» AgentState. ThÃªm StateGraph wrapper lÃ  xong.
    """

    def __init__(
        self,
        hybrid_rag: Optional["IKnowledgeStore"] = None,
        worker: Optional["ILLMClient"] = None,
        critique_agent: Optional["SelfCritiqueAgent"] = None,
        memory: Optional["ConversationMemory"] = None,
    ):
        """
        Khởi tạo ReActOrchestrator với Constructor Injection.
        """
        self._rag = hybrid_rag
        self._memory = memory
        if worker is None:
            raise ValueError("worker (ILLMClient) must be provided")
        self._worker = worker
        self._critique = critique_agent or SelfCritiqueAgent()
        self._last_sources: list = []   # Giai doan 5: theo doi nguon de DocxExporter

    def set_rag(self, hybrid_rag):
        """Inject HybridRAG sau khi khá»Ÿi táº¡o (trÃ¡nh circular dependency)."""
        self._rag = hybrid_rag

    # â”€â”€ Node 1: Truy xuáº¥t ngá»¯ cáº£nh tá»« HybridRAG â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _node_retrieve(self, state: AgentState) -> AgentState:
        """
        BÆ°á»›c 5.1 -> 5.3: Truy xuáº¥t ngá»¯ cáº£nh lai kÃ©p (Vector + Graph).

        [C1-FIX] ÄÃ£ sá»­a: dead code (try/except sau return) Ä‘Ã£ Ä‘Æ°á»£c xÃ³a vÃ 
        bá»c Ä‘Ãºng vá»‹ trÃ­ quanh lá»‡nh gá»i retrieve_context() thá»±c sá»±.
        [M1-FIX] ÄÃ£ xÃ³a _wide_retrieval dead key â€” top_k cá»‘ Ä‘á»‹nh = 5.
        """
        if self._rag is None:
            logger.warning("[ReAct:RETRIEVE] HybridRAG chÆ°a Ä‘Æ°á»£c inject. Context rá»—ng.")
            return {**state, "context_chunks": []}

        try:
            with timed(state["metrics"], "qdrant_ms"):
                context_chunks = self._rag.retrieve_context(
                    query=state["user_input"],
                    top_k=5,
                )
            state["metrics"].chunks_retrieved = len(context_chunks)
            # LÆ°u nguá»“n Ä‘á»ƒ get_last_sources() tráº£ vá» cho DocxExporter (Giai Ä‘oáº¡n 5)
            self._last_sources = list({
                c.get("source", "") for c in context_chunks if c.get("source")
            })
            logger.info(
                "[ReAct:RETRIEVE] Thu Ä‘Æ°á»£c %d chunks tá»« %d nguá»“n.",
                len(context_chunks), len(self._last_sources)
            )
            return {**state, "context_chunks": context_chunks}
        except Exception as e:
            logger.error("[ReAct:RETRIEVE] Lá»—i truy xuáº¥t RAG: %s", e, exc_info=True)
            return {**state, "context_chunks": [], "error": str(e)}

    # â”€â”€ Node 2: Cháº¥m Ä‘iá»ƒm ngá»¯ cáº£nh (Self-Critique) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _node_critique(self, state: AgentState) -> AgentState:
        """
        BÆ°á»›c 6.1: Cháº¥m Ä‘iá»ƒm cháº¥t lÆ°á»£ng ngá»¯ cáº£nh RAG.
        """
        try:
            with timed(state["metrics"], "critique_ms"):
                critique = self._critique.evaluate(
                    question=state["user_input"],
                    context_chunks=state["context_chunks"],
                )
            state["metrics"].critique_rounds += 1
            if critique:
                state["metrics"].critique_score = critique.relevance_score
            return {**state, "critique": critique}
        except Exception as e:
            logger.error(f"[ReAct:CRITIQUE] Lá»—i: {e}. Fallback proceed.")
            return {
                **state,
                "critique": SelfCritiqueResult(
                    relevance_score=7.0, answerability_score=7.0,
                    missing_information="", action_required="proceed"
                )
            }

    # â”€â”€ Node 3: TÃ¬m kiáº¿m web (DuckDuckGo) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _node_web_search(self, state: AgentState) -> AgentState:
        """
        BÆ°á»›c 6.2: KÃ­ch hoáº¡t DuckDuckGo khi ngá»¯ cáº£nh local khÃ´ng Ä‘á»§.
        Giá»›i háº¡n max_iterations=3 báº±ng cáº§u dao an toÃ n cá»©ng.
        """
        current_iter = state.get("search_iterations", 0)

        # Cáº§u dao an toÃ n cá»©ng - trÃ¡nh vÃ²ng láº·p vÃ´ táº­n
        if current_iter >= MAX_SEARCH_ITER:
            logger.warning(
                f"[ReAct:WEB_SEARCH] ÄÃ£ Ä‘áº¡t giá»›i háº¡n {MAX_SEARCH_ITER} vÃ²ng tÃ¬m kiáº¿m. "
                f"[ReAct:WEB_SEARCH] Ä Ã£ Ä‘áº¡t giá»›i háº¡n {MAX_SEARCH_ITER} vÃ²ng tÃ¬m kiáº¿m. "
                "Dá»«ng vÃ  dÃ¹ng best effort."
            )
            return {**state, "search_iterations": current_iter}

        if not DDGS_AVAILABLE:
            logger.warning("[ReAct:WEB_SEARCH] duckduckgo-search chÆ°a cÃ i. Bá»  qua.")
            return {**state, "search_iterations": current_iter + 1}

        state["metrics"].web_search_used = True

        logger.info(
            f"[ReAct:WEB_SEARCH] VÃ²ng {current_iter + 1}/{MAX_SEARCH_ITER}: "
            f"Thá»±c hiá»‡n tÃ¬m kiáº¿m web cho: {state['user_input']}"
        )

        try:
            web_texts = []
            with timed(state["metrics"], "web_search_ms"):
                with DDGS() as ddgs:
                    results = list(ddgs.text(
                        keywords=state["user_input"],
                        max_results=WEB_SEARCH_MAX_RESULTS,
                    ))
                    for r in results:
                        snippet = f"[{r.get('title', '')}]\n{r.get('body', '')}"
                        web_texts.append(snippet)

            logger.info(f"[ReAct:WEB_SEARCH] TÃ¬m Ä‘Æ°á»£c {len(web_texts)} káº¿t quáº£.")

            # Merge káº¿t quáº£ web vÃ o web_results (thÃªm vÃ o, khÃ´ng ghi Ä‘Ã¨)
            existing = state.get("web_results", [])
            return {
                **state,
                "web_results": existing + web_texts,
                "search_iterations": current_iter + 1,
            }

        except Exception as e:
            logger.error(f"[ReAct:WEB_SEARCH] Lá»—i DuckDuckGo: {e}")
            return {**state, "search_iterations": current_iter + 1}

    # â”€â”€ Node 4: Sinh cÃ¢u tráº£ lá» i cuá»‘i cÃ¹ng â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _node_generate(self, state: AgentState) -> AgentState:
        """
        BÆ°á»›c 5.3: Nhá»“i ngá»¯ cáº£nh vÃ o prompt vÃ  gá» i WorkerEngine sinh cÃ¢u tráº£ lá» i.
        """
        # [I4 FIX] Gioi han web_results truoc khi nho vao prompt
        # Sau 3 vong Ã— 5 ket qua = 15 web results co the vuot token limit 32K
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
            context_combined += f"=== TÃ i liá»‡u ná»™i bá»™ ===\n{rag_text}\n\n"
        if web_text:
            context_combined += f"=== Káº¿t quáº£ tÃ¬m kiáº¿m web ===\n{web_text}\n\n"

        if not context_combined:
            context_combined = "(KhÃ´ng tÃ¬m tháº¥y ngá»¯ cáº£nh. Tráº£ lá» i dá»±a trÃªn kiáº¿n thá»©c chung.)"

        user_prompt = f"""NGá»® Cáº¢NH:
{context_combined}

CÃ‚U Há»ŽI:
{state['user_input']}

Tráº£ lá» i báº±ng tiáº¿ng Viá»‡t há» c thuáº­t:"""

        try:
            with timed(state["metrics"], "llm_generate_ms"):
                gen = self._worker.generate(
                    system_prompt=_ANSWER_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                )
            return {**state, "final_answer": gen}
        except Exception as e:
            logger.error(f"[ReAct:GENERATE] Lá»—i WorkerEngine: {e}")
            return {
                **state,
                "final_answer": f"Xin lá»—i, há»‡ thá»‘ng gáº·p sá»± cá»‘ khi xá»­ lÃ½ cÃ¢u há» i. Lá»—i: {str(e)[:100]}",
                "error": str(e),
            }

    # â”€â”€ Ä iá» u kiá»‡n chuyá»ƒn tráº¡ng thÃ¡i â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _should_search(self, state: AgentState) -> bool:
        """BÆ°á»›c 6.2: Quyáº¿t Ä‘á»‹nh cÃ³ cáº§n web search khÃ´ng."""
        critique = state.get("critique")
        if critique is None:
            return False
        if state.get("search_iterations", 0) >= MAX_SEARCH_ITER:
            return False  # Ä Ã£ Ä‘áº¡t giá»›i háº¡n, báº¯t buá»™c generate
        return critique.action_required == "force_web_search"

    # â”€â”€ Entry point chÃ­nh â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def run(
        self,
        user_input: str,
        additional_context: Optional[List[Dict]] = None,
        intent: str = "research_query"
    ):
        """
        Cháº¡y toÃ n bá»™ luá»“ng ReAct cho má»™t cÃ¢u há» i cá»§a ngÆ°á» i dÃ¹ng.
        Giai doan 5.5: Bá»• sung intent Ä‘á»ƒ chá» n luá»“ng.
        """
        config = get_config_for_intent(intent)
        
        if intent == "daily_task":
            logger.info("[ReActOrchestrator] === Bắt đầu Fast-Track (daily_task) ===")
            import concurrent.futures

            def _get_rag() -> str:
                try:
                    if self._rag:
                        chunks = self._rag.retrieve_context(query=user_input, top_k=config.retrieve.top_k)
                        return PromptBuilder.format_rag_context(chunks)
                except Exception as e:
                    logger.error("[FastTrack] Lỗi RAG: %s", e, exc_info=True)
                return ""

            def _get_web() -> str:
                try:
                    if DDGS_AVAILABLE:
                        results = DDGS().text(user_input, max_results=3)
                        return "\n".join(f"- {r['title']}: {r['body']}" for r in results)
                except Exception as e:
                    logger.error("[FastTrack] Lỗi Web: %s", e, exc_info=True)
                return ""

            rag_text = web_text = ""
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                rag_text = executor.submit(_get_rag).result()
                web_text = executor.submit(_get_web).result()

            ctx = PromptContext(user_query=user_input, rag_context=rag_text, web_context=web_text)
            system_prompt, user_prompt = PromptBuilder.build_answer(ctx, fast=True)
            gen = self._worker.generate(system_prompt=system_prompt, user_prompt=user_prompt)
            for chunk in gen: yield chunk
            return

        # Deep-Track (research_query)
        metrics = PipelineMetrics(
            query=user_input, 
            intent=intent, 
            conversation_id=getattr(self._memory, "session_id", "")
        )
        # Khởi tạo trạng thái ban đầu
        state: AgentState = {
            "user_input": user_input,
            "context_chunks": additional_context or [],
            "web_results": [],
            "critique": None,
            "final_answer": "",
            "search_iterations": 0,
            "error": None,
            "metrics": metrics,
        }

        # [S5-FIX] Chá»‰ thÃªm "..." khi input thá»±c sá»± bá»‹ cáº¯t
        preview = user_input[:60] + ("..." if len(user_input) > 60 else "")
        logger.info("[ReActOrchestrator] === Báº¯t Ä‘áº§u xá»­ lÃ½: '%s' ===", preview)

        # â”€â”€ BÆ°á»›c 1: Truy xuáº¥t ngá»¯ cáº£nh â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        state["_is_fast"] = (intent == "daily_task")
        state = self._node_retrieve(state)

        # â”€â”€ BÆ°á»›c 2: Critique + ReAct loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # 5. Sinh cÃ¢u tráº£ lá» i (Generate)
        state = self._node_generate(state)
        
        # 6. Yield tá»«ng pháº§n (Náº¿u LLM tráº£ vá»  generator)
        import time
        t0 = time.perf_counter()
        if isinstance(state["final_answer"], str):
            metrics.llm_total_ms = (time.perf_counter() - t0) * 1000
            yield state["final_answer"]
        else:
            first = True
            for chunk in state["final_answer"]:
                if first:
                    metrics.llm_first_token_ms = (time.perf_counter() - t0) * 1000
                    first = False
                yield chunk
            metrics.llm_total_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "[ReActOrchestrator] === HoÃ n thÃ nh. "
            "Search loops=%d | Answer length=%d chars ===",
            state["search_iterations"], total_chars,
        )
        metrics.log_summary()

    def get_last_sources(self) -> list:
        """
        [Giai doan 5] Tra ve danh sach nguon (ten file) tu lan RAG gan nhat.
        Duoc dung boi DocxExporter de xay dung phan Tai Lieu Tham Khao.
        """
        return list(self._last_sources)

    def close(self):
        """Dá»n dáº¹p tÃ i nguyÃªn."""
        self._worker.close()
        gc.collect()
        logger.info("[ReActOrchestrator] ÄÃ£ dá»n sáº¡ch tÃ i nguyÃªn.")


# â”€â”€â”€ Test nhanh khi cháº¡y trá»±c tiáº¿p â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()  # Chá»‰ load khi cháº¡y file Ä‘á»™c láº­p Ä‘á»ƒ test

    print("--- Orchestrator Component Test ---")
    print("Testing SelfCritiqueResult Pydantic model...\n")

    # Test Pydantic model (khÃ´ng cáº§n API key)
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
