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

Kiến trúc Hybrid V5 (Chống False Positive tuyệt đối):
  1. Khóa chặt 2 đầu (^...$) cho các câu lệnh tiện ích (Time, Ninja UX).
  2. Bắt buộc Action-Verb Anchor (mở|tìm|lưu...) ở đầu câu cho các lệnh hệ thống.
  3. Nhường toàn bộ các câu không mang tính chất "mệnh lệnh" cho Semantic Router.
"""

import os
import re
import subprocess
import webbrowser
import logging
import urllib.parse
from datetime import datetime
from typing import Optional, Tuple, Any

logger = logging.getLogger("RegexInterceptor")

# ══════════════════════════════════════════════════════════════════════════════
#  CÁC HẰNG SỐ CẤU HÌNH
# ══════════════════════════════════════════════════════════════════════════════

OBSIDIAN_MEMORY_FILE = os.path.join("03_Agent_Memory", "Profile.md")

# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 1: Lọc câu rác khoảng lặng Whisper (STT Hallucination Filter)
# ══════════════════════════════════════════════════════════════════════════════

_WHISPER_HALLUCINATION_PATTERN = re.compile(
    r"(Cảm ơn các bạn|Xin chào các bạn|Subtitles by|Amara\.org"
    r"|Cảm ơn quý vị|Thanks for watching|Chúc một ngày tốt lành"
    r"|Hẹn gặp lại|Subscribe|Like và share|Nhớ đăng ký kênh)",
    re.IGNORECASE,
)

def filter_whisper_hallucination(audio_text: str) -> Optional[str]:
    """Lọc rác Whisper. Chỉ lọc nếu câu ngắn gọn mang tính chất lỗi STT."""
    if len(audio_text.split()) < 10 and _WHISPER_HALLUCINATION_PATTERN.search(audio_text.strip()):
        logger.info("[Interceptor] Whisper hallucination bị chặn: '%s'", audio_text[:50])
        return None
    return audio_text


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 2: Tra cứu thời gian và ngày tháng tĩnh (Khóa 2 đầu)
# ══════════════════════════════════════════════════════════════════════════════

_TIME_PATTERN = re.compile(
    r"^(?:quản gia|hãy|cho tôi biết|xem|cho biết)?\s*"
    r"(?:"
    r"bây giờ\s+(?:là\s+)?(?:mấy giờ|giờ mấy|bao nhiêu giờ|giờ nào)(?:\s+rồi)?"
    r"|(?:mấy giờ|giờ mấy|bao nhiêu giờ|giờ là mấy|giờ hiện tại|mấy giờ rồi)(?:\s+rồi)?"
    r"|hiện tại\s+(?:là\s+)?(?:mấy giờ|giờ mấy)"
    r"|(?:giờ|thời gian)\s+(?:là\s+)?(?:mấy|bao nhiêu)"
    r")"
    r"[\s\.\?!]*$",
    re.IGNORECASE | re.UNICODE,
)
_DATE_PATTERN = re.compile(
    r"^(?:quản gia|hãy|cho tôi biết|xem|cho biết)?\s*"
    r"(?:"
    r"hôm nay\s+(?:là\s+)?(?:ngày bao nhiêu|ngày mấy|ngày nào|là ngày gì)"
    r"|(?:ngày|hôm nay)\s+(?:là\s+)?(?:mấy|bao nhiêu|ngày nào)"
    r"|ngày hiện tại(?:\s+là\s+(?:ngày bao nhiêu|mấy))?"
    r"|ngày mấy\s+rồi|hôm nay ngày mấy"
    r")"
    r"[\s\.\?!]*$",
    re.IGNORECASE | re.UNICODE,
)
_DAY_PATTERN = re.compile(
    r"^(?:quản gia|hãy|cho tôi biết|xem|cho biết)?\s*"
    r"(?:hôm nay\s+)?(?:thứ mấy|thứ mấy rồi|ngày thứ mấy|thứ mấy hôm nay)"
    r"[\s\.\?!]*$",
    re.IGNORECASE | re.UNICODE,
)
_DATETIME_PATTERN = re.compile(
    r"^(?:quản gia|hãy|cho tôi biết|xem)?\s*"
    r"(?:bây giờ là mấy giờ|hiện tại mấy giờ|bây giờ ngày mấy|hôm nay thứ mấy ngày mấy)"
    r"[\s\.\?!]*$",
    re.IGNORECASE | re.UNICODE,
)

_WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

def check_time_queries(user_input: str) -> Optional[str]:
    text = user_input.strip()
    now = datetime.now()
    weekday = _WEEKDAYS_VI[now.weekday()]

    if _DATETIME_PATTERN.match(text):
        result = f"Bây giờ là {now.strftime('%H:%M')} phút, {weekday}, ngày {now.strftime('%d/%m/%Y')}."
        logger.info("[Interceptor] Datetime query → %s", result)
        return result

    if _TIME_PATTERN.match(text):
        result = f"Bây giờ là {now.strftime('%H:%M')} phút."
        logger.info("[Interceptor] Time query → %s", result)
        return result

    if _DATE_PATTERN.match(text):
        result = f"Hôm nay là {weekday}, ngày {now.strftime('%d/%m/%Y')}."
        logger.info("[Interceptor] Date query → %s", result)
        return result

    if _DAY_PATTERN.match(text):
        result = f"Hôm nay là {weekday}, ngày {now.strftime('%d/%m/%Y')}."
        logger.info("[Interceptor] Day-of-week query → %s", result)
        return result

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 3.1: Tìm kiếm web thông minh (Action-Verb Anchored)
# ══════════════════════════════════════════════════════════════════════════════

_SMART_SEARCH_PATTERN = re.compile(
    r"^(?:hãy|quản gia|mày|nhờ bạn|giúp tôi)?\s*(?:mở|tìm|kiếm|tìm kiếm|search|bật|tra)\s+(.+?)(?:\s+(?:trên|ở|trong)\s+(youtube|google|gg))?\s*$",
    re.IGNORECASE,
)

def check_smart_web_search(user_input: str) -> Optional[str]:
    match = _SMART_SEARCH_PATTERN.search(user_input.strip())
    if not match:
        return None

    query = match.group(1).strip()
    platform = match.group(2).strip().lower() if match.group(2) else None
    
    # Auto default to YouTube for multimedia queries
    if not platform:
        if re.search(r"^(bài hát|bài|video|clip|nhạc|phim)\b", query, re.IGNORECASE):
            platform = "youtube"
        else:
            return None # Trả về RAG/OS Command
            
    encoded_query = urllib.parse.quote(query)
    
    if platform == "youtube":
        url = f"https://www.youtube.com/results?search_query={encoded_query}"
        # [B7-FIX] Dung webbrowser.open thay vi 'start chrome' -> hoat dong voi moi trinh duyet
        webbrowser.open(url)
        logger.info("[Interceptor] Smart Search YouTube: %s", query)
        return f"Da tim kiem tren Youtube: {query}"
        
    elif platform in ["google", "gg"]:
        url = f"https://www.google.com/search?q={encoded_query}"
        webbrowser.open(url)
        logger.info("[Interceptor] Smart Search Google: %s", query)
        return f"Da tim kiem tren Google: {query}"

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 3: Điều khiển HĐH và khởi chạy phần mềm (Action-Verb Anchored)
# ══════════════════════════════════════════════════════════════════════════════

_OS_PATTERN = re.compile(
    r"^(?:hãy|quản gia|mày|làm ơn)?\s*(?:mở|bật|khởi động|vào|chạy)\s+"
    r"(youtube|zalo|zotero|chrome|word|thư mục|vs code|vscode|visual studio)\b.*",
    re.IGNORECASE,
)

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
    match = _OS_PATTERN.search(user_input.strip())
    if not match:
        return None

    app_keyword = match.group(1).strip().lower()

    command = None
    for key, cmd in _APP_COMMANDS.items():
        if key in app_keyword:
            command = cmd
            break

    if command:
        # [B8-FIX] Wrap trong try/except: neu app chua cai, Windows tra loi am
        # nhung subprocess khong raise exception. Log ro rang giup debug.
        try:
            result = subprocess.Popen(command, shell=True)
            logger.info("[Interceptor] OS Command: %s -> %s (PID: %s)", app_keyword, command, result.pid)
        except Exception as e:
            logger.error("[Interceptor] Khong the chay lenh OS '%s': %s", command, e)
            return f"Loi mo '{match.group(1).strip()}': {str(e)[:60]}"
        return f"Da mo {match.group(1).strip()} cho ban."


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 4: Ghi nhớ ký ức nhanh vào Obsidian (Action-Verb Anchored)
# ══════════════════════════════════════════════════════════════════════════════

_MEMORY_PATTERN = re.compile(
    r"^(?:(?:hãy|nhờ bạn|mày|quản gia|giúp tôi)\s+)?(?:lưu|nhớ|ghi nhớ|lưu lại|note|thêm vào ghi chú|ghi sổ)\b.*?(?:rằng|là|thông tin)?\s+(.+)",
    re.IGNORECASE,
)

def check_and_save_to_obsidian(user_input: str, vault_path: str) -> Optional[str]:
    match = _MEMORY_PATTERN.search(user_input.strip())
    if not match:
        return None

    content_to_save = match.group(1).strip()
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
        return f"Lỗi khi ghi Obsidian: {str(e)[:80]}"


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 5: Ép tra mạng, bỏ qua RAG local (Action-Verb Anchored)
# ══════════════════════════════════════════════════════════════════════════════

_FORCE_WEB_PATTERN = re.compile(
    r"^(?:(?:hãy|nhờ bạn|mày|quản gia|giúp tôi)\s+)?(?:tra mạng|tìm trên mạng|tìm google|bỏ qua RAG|bỏ qua dữ liệu cũ|cập nhật mạng)\s*(.*)",
    re.IGNORECASE,
)

def force_web_search_override(user_input: str) -> Optional[dict]:
    match = _FORCE_WEB_PATTERN.search(user_input.strip())
    if not match:
        return None

    query = match.group(1).strip() or user_input
    logger.info("[Interceptor] Force web search: '%s'", query[:50])
    return {"intent": "FORCE_WEB", "query": query}


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 6: Kích hoạt xuất báo cáo Word (Action-Verb Anchored)
# ══════════════════════════════════════════════════════════════════════════════

_DOCX_PATTERN = re.compile(
    r"^(?:(?:hãy|nhờ bạn|mày|quản gia|giúp tôi)\s+)?(?:xuất|lưu|tổng hợp|viết).*?(?:ra|thành|báo cáo)?\s*(?:file\s+)?(word|docx)\b\s*(.*)",
    re.IGNORECASE,
)

def trigger_docx_export(user_input: str) -> Optional[dict]:
    match = _DOCX_PATTERN.search(user_input.strip())
    if not match:
        return None

    topic = match.group(2).strip()
    logger.info("[Interceptor] Docx export triggered, topic: '%s'", topic[:50])
    return {"intent": "EXPORT_DOCX", "topic": topic}


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 7: Lệnh tương tác Ninja UX (Khóa 2 đầu cực kỳ chặt chẽ)
# ══════════════════════════════════════════════════════════════════════════════

_COPY_PATTERN = re.compile(
    r"^(?:quản gia|hãy)?\s*(?:copy|sao chép)(?:\s+(?:câu|trả lời|lại|đó))?[\s\.\?!]*$", 
    re.IGNORECASE
)
_TOAST_PATTERN = re.compile(
    r"^(?:quản gia|hãy)?\s*(?:hiện chữ|hiện text|in ra màn hình|bật thông báo text|tao chưa nghe rõ)[\s\.\?!]*$", 
    re.IGNORECASE
)
_REPEAT_PATTERN = re.compile(
    r"^(?:quản gia|hãy)?\s*(?:nói lại|đọc lại|nhắc lại|nói lại đi|đọc lại xem)(?:\s+(?:đi|xem|câu vừa rồi))?[\s\.\?!]*$", 
    re.IGNORECASE
)

def check_ninja_ux_commands(
    user_input: str,
    last_response: str = "",
) -> Optional[str]:
    text = user_input.strip()

    if _COPY_PATTERN.match(text):
        if last_response:
            try:
                import pyperclip
                pyperclip.copy(last_response)
                logger.info("[Interceptor] Đã copy vào clipboard.")
                return "Đã sao chép toàn bộ câu trả lời cuối vào bộ nhớ tạm hệ thống."
            except ImportError:
                return "Thư viện pyperclip chưa cài."
        return "Chưa có câu trả lời nào để copy."

    if _TOAST_PATTERN.match(text):
        if last_response:
            try:
                from win11toast import toast
                toast("Digital Scholar", last_response[:200], duration="long")
                logger.info("[Interceptor] Đã hiện toast notification.")
            except ImportError:
                pass
        return "Đã hiển thị khung chữ bổ trợ ở góc màn hình Windows."

    if _REPEAT_PATTERN.match(text):
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
    Cổng đánh chặn trung tâm. (Hybrid Architecture)
    Bảo đảm 0 False Positives cho RAG nhờ cơ chế Action-Verb Anchoring.
    """
    text = user_input.strip()
    if not text:
        return None, None
        
    # ── Lớp 1: Whisper hallucination
    if filter_whisper_hallucination(text) is None:
        return None, None

    # ── Lớp 2: Truy vấn thời gian/ngày tháng (Khóa 2 đầu)
    result = check_time_queries(text)
    if result:
        return result, "fast"

    # ── Lớp 7: Ninja UX (copy, toast, repeat) (Khóa 2 đầu)
    result = check_ninja_ux_commands(text, last_response)
    if result is not None:
        mode = "ninja" if result == "REPEAT_LAST_VOICE" else "fast"
        return result, mode

    # ── Lớp 3.1: Tìm kiếm web thông minh (Action Verb)
    result = check_smart_web_search(text)
    if result:
        return result, "ninja"

    # ── Lớp 3: Lệnh OS (mở app tĩnh) (Action Verb)
    result = check_os_commands(text)
    if result:
        return result, "ninja"

    # ── Lớp 4: Ghi nhớ Obsidian (Action Verb)
    if vault_path:
        result = check_and_save_to_obsidian(text, vault_path)
        if result:
            return result, "ninja"

    # ── Lớp 5: Force web search override (Action Verb)
    result = force_web_search_override(text)
    if result:
        return result, "fast"

    # ── Lớp 6: Docx export (Action Verb)
    result = trigger_docx_export(text)
    if result:
        return result, "fast"

    # TẤT CẢ các câu còn lại (không có Action Verb, không đúng pattern UX) -> RAG
    return None, None
