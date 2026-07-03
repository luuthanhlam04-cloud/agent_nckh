"""
regex_interceptor.py - Bộ Giáp Regex Đánh Chặn Cục bộ (Zero-Cost Interceptor)
=================================================================================
Vai trò trong kiến trúc (Phần 2 Chức năng 2 - last agent.md / README.md):
  Đặt tại đầu cổng xử lý, đánh chặn ~60% lệnh thông thường ngay tại
  Main Thread, tiết kiệm hoàn toàn chi phí token LLM.

Hàm điều phối chính:
  intercept(text, vault_path, last_response)
    → (result: str, mode: "fast")   → hiển thị kết quả ngay trong UI
    → (result: str, mode: "ninja")  → hide() cửa sổ + win11toast
    → (None, None)                  → không khớp, đẩy xuống AIWorker

Các module con (7 hàm theo README.md):
  1. filter_whisper_hallucination  - lọc câu rác khoảng lặng Whisper
  2. check_time_queries            - tra giờ/ngày tĩnh không tốn token
  3. check_os_commands             - mở app/web hệ thống Windows
  4. check_and_save_to_obsidian    - ghi nhanh vào Profile.md Obsidian
  5. force_web_search_override     - ép tra mạng bỏ qua RAG local
  6. trigger_docx_export           - kích hoạt xuất báo cáo Word
  7. check_ninja_ux_commands       - copy clipboard, toast, đọc lại
"""

import os
import re
import logging
from datetime import datetime
from typing import Optional, Tuple, Any

logger = logging.getLogger("RegexInterceptor")

# ══════════════════════════════════════════════════════════════════════════════
#  CÁC HẰNG SỐ CẤU HÌNH
# ══════════════════════════════════════════════════════════════════════════════

# Tên file memory trong Obsidian (Chức năng 7 - Bước 7.2 spec)
OBSIDIAN_MEMORY_FILE = "03_Agent_Memory/Profile.md"

# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 1: Lọc câu rác khoảng lặng Whisper (STT Hallucination Filter)
# ══════════════════════════════════════════════════════════════════════════════

_WHISPER_HALLUCINATION_PATTERN = re.compile(
    r"^(Cảm ơn các bạn|Xin chào các bạn|Subtitles by|Amara\.org"
    r"|Cảm ơn quý vị|Thanks for watching|Chúc một ngày tốt lành"
    r"|Hẹn gặp lại|Subscribe|Like và share|Nhớ đăng ký kênh).*",
    re.IGNORECASE,
)


def filter_whisper_hallucination(audio_text: str) -> Optional[str]:
    """
    Lọc câu rác từ khoảng lặng âm thanh của Whisper.

    Returns:
        None  nếu là câu rác → bỏ qua hoàn toàn.
        str   nếu là câu thật → tiếp tục xử lý.
    """
    if _WHISPER_HALLUCINATION_PATTERN.search(audio_text.strip()):
        logger.info("[Interceptor] Whisper hallucination bị chặn: '%s'", audio_text[:50])
        return None
    return audio_text


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 2: Tra cứu thời gian và ngày tháng tĩnh (0 token)
# ══════════════════════════════════════════════════════════════════════════════

_TIME_PATTERN = re.compile(
    r"^(mấy giờ|bây giờ là mấy giờ|giờ hiện tại|quản gia mấy giờ rồi|mấy giờ rồi).*",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"^(hôm nay là ngày bao nhiêu|hôm nay ngày mấy|ngày hiện tại|hôm nay là ngày mấy).*",
    re.IGNORECASE,
)


def check_time_queries(user_input: str) -> Optional[str]:
    """
    Trả lời câu hỏi về giờ/ngày tháng trực tiếp từ đồng hồ hệ thống.
    Không tốn 1 token nào.

    Returns:
        str  nếu khớp → kết quả trả về ngay (mode: fast).
        None nếu không khớp.
    """
    text = user_input.strip()
    now = datetime.now()

    if _TIME_PATTERN.search(text):
        result = f"Bây giờ là {now.strftime('%H:%M')} phút."
        logger.info("[Interceptor] Time query → %s", result)
        return result

    if _DATE_PATTERN.search(text):
        result = f"Hôm nay là ngày {now.strftime('%d/%m/%Y')}."
        logger.info("[Interceptor] Date query → %s", result)
        return result

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 3: Điều khiển HĐH và khởi chạy phần mềm (OS Control)
# ══════════════════════════════════════════════════════════════════════════════

_OS_PATTERN = re.compile(
    r"^(?:hãy|quản gia|mày)?\s*(mở|bật|khởi động|vào)\s+"
    r"(youtube|zalo|zotero|chrome|word|thư mục|vs code|vscode|visual studio).*",
    re.IGNORECASE,
)

# Map từ khóa → lệnh shell Windows
_APP_COMMANDS = {
    "youtube":        "start chrome https://youtube.com",
    "zalo":           "start zalo",
    "zotero":         "start zotero:",
    "chrome":         "start chrome",
    "vs code":        "code .",
    "vscode":         "code .",
    "visual studio":  "code .",
    "word":           "start winword",
    "thư mục":        "explorer .",
}


def check_os_commands(user_input: str) -> Optional[str]:
    """
    Phân tích lệnh mở ứng dụng/web và thực thi ngay bằng os.system().

    Returns:
        str  nếu khớp và đã thực thi → thông báo xác nhận (mode: ninja).
        None nếu không khớp.
    """
    match = _OS_PATTERN.search(user_input.strip())
    if not match:
        return None

    app_keyword = match.group(2).strip().lower()

    # Tìm lệnh phù hợp nhất trong map
    command = None
    for key, cmd in _APP_COMMANDS.items():
        if key in app_keyword:
            command = cmd
            break

    if command:
        os.system(command)
        logger.info("[Interceptor] OS Command: %s → %s", app_keyword, command)
        return f"Đã mở {match.group(2).strip()} cho sếp."

    logger.warning("[Interceptor] Không tìm thấy lệnh cho app: %s", app_keyword)
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 4: Ghi nhớ ký ức nhanh vào Obsidian (Long-term Memory Update)
# ══════════════════════════════════════════════════════════════════════════════

_MEMORY_PATTERN = re.compile(
    r"^(?:hãy|nhờ bạn|mày|quản gia|giúp tôi)?\s*"
    r"(lưu|nhớ|ghi nhớ|lưu lại|lưu thông tin|note lại|thêm vào ghi chú"
    r"|nhớ giúp tôi|ghi vào sổ|nhớ là)\s*"
    r"(?:rằng|là|thông tin)?\s+(.+)",
    re.IGNORECASE,
)


def check_and_save_to_obsidian(user_input: str, vault_path: str) -> Optional[str]:
    """
    Ghi nội dung nhanh vào file Profile.md trong Obsidian Vault.
    Chạy hoàn toàn cục bộ, không tốn token.

    Returns:
        str  nếu khớp và đã ghi → thông báo xác nhận (mode: ninja).
        None nếu không khớp.
    """
    match = _MEMORY_PATTERN.search(user_input.strip())
    if not match:
        return None

    content_to_save = match.group(2).strip()
    memory_file = os.path.join(vault_path, OBSIDIAN_MEMORY_FILE)

    try:
        os.makedirs(os.path.dirname(memory_file), exist_ok=True)
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n- [{timestamp}]: {content_to_save}")
        logger.info("[Interceptor] Đã ghi vào Obsidian: '%s'", content_to_save[:50])
        return f"Đã ghi nhớ vào Obsidian: {content_to_save}"
    except Exception as e:
        logger.error("[Interceptor] Lỗi ghi Obsidian: %s", e)
        return f"Lỗi khi ghi vào Obsidian: {str(e)[:80]}"


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 5: Ép tra mạng, bỏ qua RAG local (Force Web Search Override)
# ══════════════════════════════════════════════════════════════════════════════

_FORCE_WEB_PATTERN = re.compile(
    r"(tra mạng bắt buộc|bỏ qua dữ liệu cũ|tìm trên mạng"
    r"|tìm trên google|search google|cập nhật mạng ngay)\s*(.*)",
    re.IGNORECASE,
)


def force_web_search_override(user_input: str) -> Optional[dict]:
    """
    Phát hiện lệnh ép tra mạng bỏ qua kho RAG cục bộ.

    Returns:
        dict {"intent": "FORCE_WEB", "query": str} nếu khớp.
        None nếu không khớp.
    """
    match = _FORCE_WEB_PATTERN.search(user_input.strip())
    if not match:
        return None

    query = match.group(2).strip() or user_input
    logger.info("[Interceptor] Force web search: '%s'", query[:50])
    return {"intent": "FORCE_WEB", "query": query}


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 6: Kích hoạt xuất báo cáo Word (.docx)
# ══════════════════════════════════════════════════════════════════════════════

_DOCX_PATTERN = re.compile(
    r"(xuất ra word|xuất báo cáo|lưu thành file word"
    r"|tổng hợp thành file word|viết báo cáo word)\s*(.*)",
    re.IGNORECASE,
)


def trigger_docx_export(user_input: str) -> Optional[dict]:
    """
    Phát hiện lệnh kích hoạt xuất báo cáo học thuật ra .docx.

    Returns:
        dict {"intent": "EXPORT_DOCX", "topic": str} nếu khớp.
        None nếu không khớp.
    """
    match = _DOCX_PATTERN.search(user_input.strip())
    if not match:
        return None

    topic = match.group(2).strip()
    logger.info("[Interceptor] Docx export triggered, topic: '%s'", topic[:50])
    return {"intent": "EXPORT_DOCX", "topic": topic}


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 7: Lệnh tương tác Ninja UX (copy, toast, đọc lại)
# ══════════════════════════════════════════════════════════════════════════════

_COPY_PATTERN = re.compile(
    r"^(copy câu vừa rồi|sao chép câu trả lời|sao chép lại).*",
    re.IGNORECASE,
)
_TOAST_PATTERN = re.compile(
    r"^(hiện chữ lên|bật thông báo text|tao chưa nghe rõ|hiện text|hiện lên màn hình).*",
    re.IGNORECASE,
)
_REPEAT_PATTERN = re.compile(
    r"^(nói lại xem|đọc lại câu vừa rồi|quản gia đọc lại|nhắc lại đi).*",
    re.IGNORECASE,
)


def check_ninja_ux_commands(
    user_input: str,
    last_response: str = "",
) -> Optional[str]:
    """
    Xử lý các lệnh tiện ích Ninja UX:
      - "copy câu vừa rồi" → copy vào clipboard Windows
      - "hiện chữ lên"     → toast notification win11toast
      - "đọc lại xem"      → trả về sentinel REPEAT_LAST_VOICE

    Returns:
        str  nếu khớp.
        None nếu không khớp.
    """
    text = user_input.strip()

    # Lệnh copy clipboard
    if _COPY_PATTERN.search(text):
        if last_response:
            try:
                import pyperclip
                pyperclip.copy(last_response)
                logger.info("[Interceptor] Đã copy vào clipboard (%d ký tự).", len(last_response))
                return "Đã sao chép toàn bộ câu trả lời cuối vào bộ nhớ tạm hệ thống."
            except ImportError:
                return "Thư viện pyperclip chưa cài. Hãy chạy: pip install pyperclip"
        return "Chưa có câu trả lời nào để copy."

    # Lệnh hiện toast text
    if _TOAST_PATTERN.search(text):
        if last_response:
            try:
                from win11toast import toast
                toast("Digital Scholar", last_response[:200], duration="long")
                logger.info("[Interceptor] Đã hiện toast notification.")
            except ImportError:
                logger.warning("[Interceptor] win11toast chưa cài.")
        return "Đã hiển thị khung chữ bổ trợ ở góc màn hình Windows."

    # Lệnh đọc lại (sentinel cho TTS)
    if _REPEAT_PATTERN.search(text):
        logger.info("[Interceptor] Repeat last voice triggered.")
        return "REPEAT_LAST_VOICE"

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  HÀM ĐIỀU PHỐI CHÍNH - intercept()
# ══════════════════════════════════════════════════════════════════════════════

def intercept(
    user_input: str,
    vault_path: str = "",
    last_response: str = "",
) -> Tuple[Optional[Any], Optional[str]]:
    """
    Cổng đánh chặn trung tâm. Gọi hàm này TRƯỚC khi đẩy vào AIWorker.

    Thứ tự ưu tiên:
      1. Whisper hallucination filter
      2. Time/Date queries       (fast)
      3. Ninja UX commands       (ninja/fast)
      4. OS commands             (ninja)
      5. Save to Obsidian        (ninja)
      6. Force web search        (fast - caller nhận dict)
      7. Docx export             (fast - caller nhận dict)

    Args:
        user_input    : Văn bản người dùng nhập.
        vault_path    : Đường dẫn gốc Obsidian Vault (cho Module 4).
        last_response : Câu trả lời AI gần nhất trong RAM (cho Module 7).

    Returns:
        (result, mode)
        - (None, None)   → không khớp, đẩy xuống LLM
        - (str,  "fast") → hiển thị trong UI, giữ cửa sổ
        - (str,  "ninja")→ hide() cửa sổ + win11toast nếu cần
        - (dict, "fast") → caller xử lý dict (FORCE_WEB, EXPORT_DOCX)
    """
    text = user_input.strip()
    if not text:
        return None, None

    # ── Lớp 1: Whisper hallucination ──────────────────────────────────────────
    if filter_whisper_hallucination(text) is None:
        return "", "ninja"  # Ẩn cửa sổ, không hiển thị gì

    # ── Lớp 2: Truy vấn thời gian/ngày tháng ─────────────────────────────────
    result = check_time_queries(text)
    if result:
        return result, "fast"

    # ── Lớp 3: Ninja UX (copy, toast, repeat) ────────────────────────────────
    result = check_ninja_ux_commands(text, last_response)
    if result is not None:
        mode = "ninja" if result == "REPEAT_LAST_VOICE" else "fast"
        return result, mode

    # ── Lớp 4: Lệnh OS (mở app, mở web) ─────────────────────────────────────
    result = check_os_commands(text)
    if result:
        return result, "ninja"

    # ── Lớp 5: Ghi nhớ Obsidian ──────────────────────────────────────────────
    if vault_path:
        result = check_and_save_to_obsidian(text, vault_path)
        if result:
            return result, "ninja"

    # ── Lớp 6: Force web search override ─────────────────────────────────────
    result = force_web_search_override(text)
    if result:
        return result, "fast"

    # ── Lớp 7: Docx export ────────────────────────────────────────────────────
    result = trigger_docx_export(text)
    if result:
        return result, "fast"

    # Không khớp bất kỳ lớp nào → đẩy xuống LLM
    return None, None
