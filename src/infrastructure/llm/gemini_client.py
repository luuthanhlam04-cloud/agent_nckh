import logging
import gc
from typing import Optional, Generator

import google.genai as genai
from src.core.interfaces import ILLMClient
from src.shared.config import GEMINI_API_KEY, WORKER_MODEL

logger = logging.getLogger("GeminiLLMClient")

class GeminiLLMClient(ILLMClient):
    """
    Gọi Gemini trực tiếp qua Google GenAI SDK.
    Hỗ trợ streaming output (Generator).
    """

    def __init__(self, model: str = WORKER_MODEL):
        self.model = model
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        """Lazy-init Gemini client."""
        if self._client is None:
            if not GEMINI_API_KEY or "điền" in GEMINI_API_KEY.lower():
                raise ValueError(
                    "[GeminiLLMClient] GEMINI_API_KEY chưa được điền vào .env!"
                )
            self._client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info(f"[GeminiLLMClient] Gemini client sẵn sàng. Model: {self.model}")
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs
    ) -> Generator[str, None, None]:
        """
        Sinh câu trả lời từ Gemini (Streaming).
        """
        client = self._get_client()
        logger.info(f"[GeminiLLMClient] Gọi {self.model} trực tiếp...")

        try:
            response_stream = client.models.generate_content_stream(
                model=self.model,
                contents=user_prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            error_msg = str(e)
            if "safety" in error_msg.lower() or "SAFETY" in error_msg:
                logger.warning("[GeminiLLMClient] Kích hoạt bộ lọc an toàn. Trả thông báo.")
                yield (
                    "Tài liệu nghiên cứu chuyên ngành chứa thuật ngữ nhạy cảm "
                    "bị bộ lọc an toàn từ chối xử lý. Vui lòng thử diễn đạt lại câu hỏi."
                )
                return
            logger.error("[GeminiLLMClient] Lỗi gọi API: %s", e, exc_info=True)
            yield f"Hệ thống lõi gặp sự cố kết nối API: {str(e)[:100]}. Vui lòng thử lại sau."

    def close(self):
        """Giải phóng client sau khi dùng."""
        if self._client:
            self._client = None
            gc.collect()
