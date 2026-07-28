import logging
import gc
from typing import Optional, Generator

from openai import OpenAI
from src.core.interfaces import ILLMClient
from src.shared.config import OPENROUTER_API_KEY, WORKER_MODEL

logger = logging.getLogger("OpenRouterLLMClient")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

class OpenRouterLLMClient(ILLMClient):
    """
    Gọi các LLM mạnh (Gemini Pro, Claude Sonnet...) qua cổng OpenRouter.
    Hỗ trợ streaming output (Generator).
    """

    def __init__(self, model: str = WORKER_MODEL):
        self.model = model
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        """Lazy-init OpenAI client trỏ về OpenRouter endpoint."""
        if self._client is None:
            if not OPENROUTER_API_KEY or "điền" in OPENROUTER_API_KEY.lower():
                raise ValueError(
                    "[OpenRouterLLMClient] OPENROUTER_API_KEY chưa được điền vào .env!"
                )
            self._client = OpenAI(
                base_url=OPENROUTER_BASE,
                api_key=OPENROUTER_API_KEY,
            )
            logger.info(f"[OpenRouterLLMClient] OpenRouter client sẵn sàng. Model: {self.model}")
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
        Sinh câu trả lời từ LLM thông qua OpenRouter (Streaming).
        """
        client = self._get_client()
        logger.info(f"[OpenRouterLLMClient] Gọi {self.model} qua OpenRouter...")

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
            error_msg = str(e)
            if "safety" in error_msg.lower() or "SAFETY" in error_msg:
                logger.warning("[OpenRouterLLMClient] Kích hoạt bộ lọc an toàn. Trả thông báo.")
                yield (
                    "Tài liệu nghiên cứu chuyên ngành chứa thuật ngữ nhạy cảm "
                    "bị bộ lọc an toàn từ chối xử lý. Vui lòng thử diễn đạt lại câu hỏi."
                )
                return
            logger.error("[OpenRouterLLMClient] Lỗi gọi API: %s", e, exc_info=True)
            yield f"Hệ thống lõi gặp sự cố kết nối API: {str(e)[:100]}. Vui lòng thử lại sau."

    def close(self):
        """Giải phóng client sau khi dùng."""
        if self._client:
            self._client = None
            gc.collect()
