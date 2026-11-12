import logging
import gc
from typing import Optional, Generator

from src.core.interfaces import ILLMClient

logger = logging.getLogger("FailoverLLMClient")


class FailoverLLMClient(ILLMClient):
    """
    LLM Client tự động chuyển vùng dự phòng (Auto-Failover).
    Thử nghiệm gọi Primary (OpenRouter) trước; nếu gặp lỗi hạn ngạch (402, 403)
    hoặc lỗi kết nối/mạng, tự động chuyển sang Secondary (Gemini Direct)
    để đảm bảo hệ thống không bao giờ bị gián đoạn luồng sinh câu trả lời.
    """

    def __init__(self, primary: ILLMClient, secondary: ILLMClient):
        self.primary = primary
        self.secondary = secondary

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> Generator[str, None, None]:
        has_content = False
        primary_failed = False
        error_reason = ""

        try:
            logger.info("[FailoverLLM] Đang thử sinh câu trả lời qua Primary engine...")
            gen = self.primary.generate(system_prompt, user_prompt, **kwargs)
            for chunk in gen:
                # Kiểm tra thông báo lỗi bị yield dạng string từ OpenRouter
                if (
                    "sự cố kết nối API" in chunk
                    or "Key limit exceeded" in chunk
                    or "Error code: 403" in chunk
                    or "Error code: 402" in chunk
                ):
                    primary_failed = True
                    error_reason = chunk
                    break
                has_content = True
                yield chunk

        except Exception as e:
            primary_failed = True
            error_reason = str(e)

        if primary_failed or not has_content:
            logger.warning(
                f"[FailoverLLM] Primary engine thất bại ({error_reason[:100]}). "
                "Tự động chuyển tiếp sang Secondary Engine (Gemini Direct)..."
            )
            try:
                yield "*(Đang chuyển tiếp sang LLM dự phòng)*\n\n"
                secondary_gen = self.secondary.generate(system_prompt, user_prompt, **kwargs)
                for chunk in secondary_gen:
                    yield chunk
            except Exception as e:
                logger.error(f"[FailoverLLM] Secondary engine cũng thất bại: {e}")
                yield f"Cả hai động cơ suy luận đều gặp sự cố: {str(e)[:100]}"

    def close(self):
        try:
            self.primary.close()
        except Exception as e:
            logger.warning("[FailoverLLMClient] Lỗi đóng primary client: %s", e)
        try:
            self.secondary.close()
        except Exception as e:
            logger.warning("[FailoverLLMClient] Lỗi đóng secondary client: %s", e)
        gc.collect()

