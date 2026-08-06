from src.shared.config import (
    GEMINI_API_KEY, 
    OPENROUTER_API_KEY, 
    VOYAGE_API_KEY,
    OBSIDIAN_VAULT_PATH
)

_REQUIRED = {
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
    "VOYAGE_API_KEY": VOYAGE_API_KEY,
    "OBSIDIAN_VAULT_PATH": OBSIDIAN_VAULT_PATH,
}

def validate() -> None:
    """
    Gọi 1 lần khi boot. Raise RuntimeError ngay nếu thiếu config quan trọng.
    Không để app khởi động với config rỗng rồi lỗi ở runtime.
    """
    missing = [k for k, v in _REQUIRED.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Please check your .env file."
        )
