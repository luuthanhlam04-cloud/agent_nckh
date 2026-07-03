"""
semantic_router.py - Bộ Định tuyến Ý định Ngữ nghĩa (Semantic Router)
=======================================================================
Vai trò trong kiến trúc (Phần 2.3 - last agent.md):
  Nhận câu hỏi thô của người dùng + lịch sử hội thoại (N=5 cặp gần nhất)
  -> Gọi Gemini Flash API với JSON Mode
  -> Trả về JSON chuẩn hóa theo API Contract 8.1

Hai cơ chế cốt lõi:
  1. ConversationMemory : Cửa sổ trượt (Sliding Window N=5) lưu trên RAM
                          Khi có câu thứ 6 -> pop câu đầu tiên.
                          Giúp LLM nội suy thực thể ẩn ("nó" ở câu 2 = "GraphRAG" ở câu 1).

  2. AutoCorrection     : 3 lớp phòng vệ chống JSON lỏ của LLM:
     Lớp 1 (API level) : response_mime_type="application/json" -> ép JSON Mode ở máy chủ.
     Lớp 2 (Regex)     : Cắt phăng text rác bọc ngoài chuỗi JSON {...} hoặc [...].
     Lớp 3 (Retry)     : Nếu Pydantic parse thất bại, ném lỗi ngược lại Gemini bắt tự sửa.
                          Giới hạn tối đa MAX_CORRECTION_RETRIES=3 lần.
"""

import os
import re
import json
import logging
from collections import deque
from typing import Optional, List, Dict, Any

import google.genai as genai
from google.genai import types as genai_types
from pydantic import BaseModel, Field, model_validator
from dotenv import load_dotenv

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SemanticRouter")

# ─── Config ───────────────────────────────────────────────────────────────────
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ROUTER_MODEL = "gemini-1.5-flash"          # Model nhanh, rẻ, dùng làm cổng lọc
SLIDING_WINDOW_SIZE = 5                    # N=5 cặp Q&A gần nhất giữ trên RAM
MAX_CORRECTION_RETRIES = 3                 # Giới hạn vòng sửa JSON lỗi

# Các loại intent hợp lệ (dễ mở rộng: thêm loại mới chỉ cần thêm vào list)
VALID_INTENT_TYPES = {"research_query", "os_control", "daily_task", "export_docx"}


# ══════════════════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS - API Contract 8.1 (last agent.md Phần 8)
# ══════════════════════════════════════════════════════════════════════════════

class OsActionPayload(BaseModel):
    """Tham số điều khiển ứng dụng hệ thống (khi intent_type = 'os_control')."""
    app_name: Optional[str] = Field(None, description="Tên ứng dụng cần mở")
    action: str = Field("open", description="Hành động thực thi")
    url: Optional[str] = Field(None, description="URL nếu mở trình duyệt web")


class RouterIntent(BaseModel):
    """
    Cấu trúc JSON chuẩn hóa đầu ra của Semantic Router.
    Ánh xạ trực tiếp từ API Contract 8.1 trong last agent.md.
    """
    intent_type: str = Field(
        ...,
        description="Phân loại ý định: research_query | os_control | daily_task | export_docx"
    )
    target_folder: Optional[List[str]] = Field(
        None,
        description="Danh sách đường dẫn thư mục Obsidian cần quét RAG. Null nếu không phải research_query."
    )
    enable_web_search: bool = Field(
        False,
        description="Cho phép LangGraph kích hoạt DuckDuckGo nếu local thiếu dữ liệu."
    )
    os_action_payload: Optional[OsActionPayload] = Field(
        None,
        description="Tham số điều khiển OS. Null nếu không phải os_control."
    )
    translated_keywords: Optional[List[str]] = Field(
        None,
        description="Danh sách từ khóa tiếng Anh đã dịch để query Neo4j (Bước 5.1)."
    )
    topic: Optional[str] = Field(
        None,
        description="Chủ đề xuất báo cáo Word (khi intent_type = 'export_docx')."
    )

    @model_validator(mode="after")
    def validate_intent(self):
        """Kiểm tra intent_type hợp lệ và tự sửa nếu cần."""
        if self.intent_type not in VALID_INTENT_TYPES:
            logger.warning(
                f"[Router] intent_type '{self.intent_type}' không hợp lệ. "
                f"Fallback sang 'research_query'."
            )
            self.intent_type = "research_query"
        return self


# ══════════════════════════════════════════════════════════════════════════════
#  ConversationMemory - Cửa sổ trượt (Sliding Window N=5)
# ══════════════════════════════════════════════════════════════════════════════

class ConversationMemory:
    """
    Quản lý bộ nhớ ngắn hạn hội thoại trên RAM bằng cơ chế Cửa sổ trượt.

    Spec (last agent.md Bước 7.1):
      "Duy trì mảng Dictionary chứa đúng lịch sử 5 cặp chat gần nhất.
       Khi xuất hiện câu chat thứ 6, câu thứ 1 tự động bị Pop/Delete khỏi RAM."

    Lý do dùng deque(maxlen=N):
      - Python tự động pop phần tử cũ nhất khi deque đầy.
      - Không cần viết thêm logic xóa thủ công.
      - Thread-safe cho thao tác append/pop đơn.
    """

    def __init__(self, max_size: int = SLIDING_WINDOW_SIZE):
        self._window: deque = deque(maxlen=max_size)
        self.last_response: str = ""  # Lưu câu trả lời cuối để phục vụ lệnh "copy câu vừa rồi"

    def add(self, user_input: str, agent_response: str):
        """Thêm một cặp Q&A mới vào cửa sổ trượt."""
        self._window.append({
            "role_user": user_input,
            "role_agent": agent_response,
        })
        self.last_response = agent_response

    def get_context_string(self) -> str:
        """
        Kết xuất lịch sử hội thoại thành chuỗi văn bản để nhúng vào prompt.
        Spec Bước 3.1: "Mã Python lôi mảng biến chứa tối đa 5 cặp Hỏi-Đáp gần nhất
                        từ RAM ghép nối vào câu lệnh mới làm dữ liệu mồi đầu vào."
        """
        if not self._window:
            return ""
        lines = ["=== Lịch sử hội thoại gần nhất ==="]
        for i, pair in enumerate(self._window, 1):
            lines.append(f"[{i}] Người dùng: {pair['role_user']}")
            lines.append(f"    Trợ lý: {pair['role_agent'][:200]}...")  # Cắt bớt cho tiết kiệm token
        return "\n".join(lines)

    def clear(self):
        """Xóa toàn bộ bộ nhớ ngắn hạn (dùng khi dọn rác nửa đêm)."""
        self._window.clear()
        self.last_response = ""

    def __len__(self) -> int:
        return len(self._window)


# ══════════════════════════════════════════════════════════════════════════════
#  SemanticRouter - Bộ định tuyến ý định chính
# ══════════════════════════════════════════════════════════════════════════════

# System prompt cố định cho Gemini Flash làm cổng lọc
_ROUTER_SYSTEM_PROMPT = """Bạn là bộ định tuyến ý định (Semantic Router) cho hệ thống trợ lý học thuật Digital Scholar.
Nhiệm vụ: Phân tích câu hỏi người dùng và LỊCH SỬ HỘI THOẠI, trả về JSON hợp lệ.

Các loại intent:
- "research_query"  : Câu hỏi học thuật, nghiên cứu, cần tra cứu tài liệu nội bộ.
- "os_control"      : Lệnh mở ứng dụng (Youtube, Zotero, VS Code, Chrome, Word...).
- "daily_task"      : Tác vụ thường ngày (xem giờ, thời tiết, lịch trình...).
- "export_docx"     : Yêu cầu tổng hợp và xuất báo cáo ra file Word (.docx).

Trả về JSON theo cấu trúc:
{
  "intent_type": "research_query" | "os_control" | "daily_task" | "export_docx",
  "target_folder": ["02_Knowledge/SubFolder1"] hoặc null,
  "enable_web_search": true | false,
  "os_action_payload": {"app_name": "...", "action": "open", "url": null} hoặc null,
  "translated_keywords": ["keyword_en_1", "keyword_en_2"] hoặc null,
  "topic": "chủ đề báo cáo" hoặc null
}

LƯU Ý QUAN TRỌNG:
- Dùng lịch sử hội thoại để nội suy thực thể ẩn (ví dụ "nó", "phương pháp đó"...).
- Dịch các từ khóa học thuật sang tiếng Anh chuyên ngành cho trường "translated_keywords".
- Chỉ trả về JSON thuần túy, KHÔNG thêm markdown, KHÔNG thêm giải thích."""


class SemanticRouter:
    """
    Bộ định tuyến ngữ nghĩa sử dụng Gemini Flash API với JSON Mode bắt buộc.

    Luồng xử lý (Bước 3.1 -> 3.3 trong last agent.md):
      Input: user_input + ConversationMemory
        ↓
      Bước 3.1 [Contextual Stitching]: Ghép lịch sử 5 cặp Q&A vào prompt mồi
        ↓
      Bước 3.2 [JSON Mode Invocating]: Gọi Gemini Flash, kích hoạt response_mime_type
        ↓
      Bước 3.3 [Routing Resolution]: Parse JSON -> RouterIntent -> rẽ nhánh hệ thống
    """

    def __init__(self):
        self._model = None

    def _get_model(self):
        """Lazy-init Gemini Flash client (google.genai SDK)."""
        if self._model is None:
            if not GEMINI_API_KEY or "điền" in GEMINI_API_KEY.lower():
                raise ValueError(
                    "[SemanticRouter] GEMINI_API_KEY chưa được điền vào .env!"
                )
            self._model = genai.Client(api_key=GEMINI_API_KEY)
            logger.info(f"[SemanticRouter] Gemini client '{ROUTER_MODEL}' đã sẵn sàng.")
        return self._model

    def route(
        self,
        user_input: str,
        memory: Optional[ConversationMemory] = None,
    ) -> RouterIntent:
        """
        Phân tích câu hỏi và trả về RouterIntent.

        Args:
            user_input : Câu hỏi hiện tại của người dùng.
            memory     : ConversationMemory chứa lịch sử hội thoại (optional).

        Returns:
            RouterIntent đã được validate bởi Pydantic.
        """
        # Bước 3.1: Contextual Stitching - ghép lịch sử vào prompt
        context_str = memory.get_context_string() if memory else ""

        prompt = f"""{context_str}

=== Câu hỏi hiện tại ===
{user_input}

Phân tích và trả về JSON routing:"""

        logger.info(f"[SemanticRouter] Routing: '{user_input[:60]}...' (memory={len(memory) if memory else 0} pairs)")

        # Bước 3.2 + 3.3: Gọi API với Auto-Correction 3 lớp
        raw_json = self._call_with_autocorrect(prompt, user_input)
        intent = RouterIntent.model_validate(raw_json)
        return intent

    def _call_with_autocorrect(
        self,
        prompt: str,
        original_input: str,
    ) -> Dict[str, Any]:
        """
        Gọi Gemini Flash với cơ chế tự sửa lỗi JSON 3 lớp.
        """
        client = self._get_model()
        last_error = None
        current_prompt = prompt
        system_prompt_combined = _ROUTER_SYSTEM_PROMPT + "\n\n" + current_prompt

        for attempt in range(1, MAX_CORRECTION_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=ROUTER_MODEL,
                    contents=system_prompt_combined,
                    config=genai_types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                        max_output_tokens=512,
                    ),
                )
                raw_text = response.text.strip()

                # Lớp 2: Regex bóc JSON khỏi text rác bọc ngoài
                cleaned = self._strip_to_json(raw_text)

                # Parse thử
                parsed = json.loads(cleaned)
                if attempt > 1:
                    logger.info(f"[SemanticRouter] Auto-Correction thành công ở lần {attempt}.")
                return parsed

            except json.JSONDecodeError as e:
                # Loi parse JSON thuat su -> retry voi Gemini tu sua
                last_error = f"JSON parse error: {e}"
                logger.warning(
                    "[SemanticRouter] Lan %d/%d: JSON loi: %s. Dang yeu cau Gemini tu sua...",
                    attempt, MAX_CORRECTION_RETRIES, last_error[:80],
                )
                # Lop 3: Nem loi nguoc lai cho Gemini tu sua
                system_prompt_combined = (
                    _ROUTER_SYSTEM_PROMPT + "\n\n" + prompt +
                    f"\n\n[Loi lan truoc]: JSON khong hop le: {last_error}\n"
                    f"[Yeu cau]: Sua lai va chi tra ve JSON thuan tuy."
                )
            except Exception as e:
                # Loi mang/API that su -> khong retry, raise ngay
                logger.error("[SemanticRouter] Loi mang/API khong mong muon: %s", e)
                break   # Thoat vong retry, dung fallback intent

        logger.error(
            f"[SemanticRouter] Thất bại sau {MAX_CORRECTION_RETRIES} lần. "
            f"Dùng fallback intent. Lỗi cuối: {last_error}"
        )
        return self._fallback_intent(original_input)

    @staticmethod
    def _strip_to_json(text: str) -> str:
        """
        Lớp 2 Auto-Correction: Dùng Regex bóc chuỗi JSON thuần túy
        khỏi markdown wrapper (```json ... ```) hoặc text rác bọc ngoài.
        """
        # Xóa markdown code block wrapper nếu có
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)

        # Tìm JSON object hoặc array đầu tiên trong text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0)

        # Thử tìm JSON array
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return match.group(0)

        return text.strip()

    @staticmethod
    def _fallback_intent(user_input: str) -> Dict[str, Any]:
        """
        Trả về intent mặc định khi Auto-Correction thất bại hoàn toàn.
        Luôn fallback về research_query để không mất câu hỏi của người dùng.
        """
        return {
            "intent_type": "research_query",
            "target_folder": None,
            "enable_web_search": True,  # Bật web search khi không chắc chắn
            "os_action_payload": None,
            "translated_keywords": user_input.split()[:5],  # Dùng từ đầu làm keyword tạm
            "topic": None,
        }


# ─── Test nhanh khi chạy trực tiếp ───────────────────────────────────────────
if __name__ == "__main__":
    import sys

    print("--- SemanticRouter Quick Test ---")
    print("NOTE: Requires GEMINI_API_KEY in .env to test routing.")
    print("Testing ConversationMemory only...\n")

    # Test ConversationMemory (không cần API key)
    mem = ConversationMemory(max_size=5)
    for i in range(7):
        mem.add(f"Question {i+1}", f"Answer {i+1}")

    print(f"Added 7 pairs to memory (maxsize=5). Current size: {len(mem)}")
    assert len(mem) == 5, "Sliding window should cap at 5!"
    print("Sliding window test PASSED - correctly capped at 5 pairs.")
    print("\nContext string preview (ASCII only):")
    # Print ASCII-safe version to avoid CP1252 issues
    ctx = mem.get_context_string()
    print(ctx.encode('ascii', errors='replace').decode('ascii')[:300])

    # Test RouterIntent Pydantic validation
    print("\n--- Testing Pydantic validation ---")
    test_data = {
        "intent_type": "invalid_type",  # Sẽ bị fallback về research_query
        "target_folder": None,
        "enable_web_search": False,
        "os_action_payload": None,
        "translated_keywords": ["test"],
        "topic": None,
    }
    intent = RouterIntent.model_validate(test_data)
    assert intent.intent_type == "research_query", "Fallback validation failed!"
    print("Pydantic auto-correction test PASSED - invalid intent fallback to 'research_query'.")

    print("\nAll tests passed!")
