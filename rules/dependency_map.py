"""
rules/dependency_map.py — Layer topology cho Dependency Direction check.

Thay đổi map này khi thêm module mới vào dự án.
Foundation (layer 0) không được import bất kỳ layer nào.
Dependency phải hướng xuống (layer cao → layer thấp).
"""

# Layer order: số CÀNG LỚN = layer CÀNG CAO (Presentation)
# Foundation = 0 (không import ai)
LAYER_ORDER: dict[str, int] = {
    "src/ui":       4,   # Presentation — layer cao nhất
    "src/db":       3,   # Infrastructure
    "src/core":     2,   # Application
    "src/services": 2,   # Application (cùng cấp với core)
    "src/utils":    0,   # Foundation — cross-cutting, không kiểm tra direction
    "src/shared":   0,   # Foundation — cross-cutting, không kiểm tra direction
}

# Packages được phép import từ bất kỳ layer nào (standard lib, third-party)
ALWAYS_ALLOWED_PREFIXES: tuple[str, ...] = (
    # Standard library
    "os", "sys", "re", "gc", "io", "abc", "ast", "time", "uuid",
    "json", "math", "enum", "typing", "pathlib", "logging", "datetime",
    "threading", "asyncio", "collections", "contextlib", "dataclasses",
    "functools", "itertools", "subprocess", "concurrent",
    # Third-party (không phải internal module)
    "PyQt6", "openai", "google", "qdrant_client", "neo4j",
    "sentence_transformers", "numpy", "fitz", "pptx", "docx",
    "watchdog", "apscheduler", "pyaudio", "edge_tts",
    "pyperclip", "keyboard", "win11toast", "ddgs",
    "pydantic", "dotenv",
)


def get_layer(filepath: str) -> int:
    """
    Xác định layer của một file dựa trên đường dẫn.
    Trả về -1 nếu file không thuộc layer nào đã định nghĩa.
    """
    norm = filepath.replace("\\", "/")
    for prefix, layer in LAYER_ORDER.items():
        if f"/{prefix}/" in norm or norm.endswith(f"/{prefix}"):
            return layer
    # File ở root (main.py, production_check.py) — không kiểm tra
    return -1


def is_internal_import(module_name: str) -> bool:
    """Kiểm tra xem import có phải internal module của dự án không."""
    if not module_name:
        return False
    # Internal module bắt đầu bằng "src."
    return module_name.startswith("src.")


def get_import_layer(module_name: str) -> int:
    """Xác định layer của module được import."""
    if not module_name:
        return -1
    for prefix, layer in LAYER_ORDER.items():
        # "src.ui.spotlight" → matches "src/ui"
        dot_prefix = prefix.replace("/", ".")
        if module_name.startswith(dot_prefix):
            return layer
    return -1
