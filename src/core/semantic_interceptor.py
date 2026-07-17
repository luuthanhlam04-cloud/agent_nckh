"""
semantic_interceptor.py - Bộ Giáp Ngữ Nghĩa (Semantic Interceptor)
===================================================================
Sử dụng mô hình e5-base (768 chiều) để phân loại ý định người dùng bằng Semantic Similarity.
Giải quyết triệt để lỗi False Negative của Regex cũ.
"""

import os
import re
import json
import math
import subprocess
import webbrowser
import logging
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional, Tuple, Any, Callable, List

logger = logging.getLogger("SemanticInterceptor")

OBSIDIAN_MEMORY_FILE = os.path.join("03_Agent_Memory", "Profile.md")
THRESHOLD = 0.87  # Ngưỡng Cosine Similarity để quyết định (Tuned for False Positives vs False Negatives)

# ══════════════════════════════════════════════════════════════════════════════
#  TẬP NEO NGỮ NGHĨA (ANCHORS)
# ══════════════════════════════════════════════════════════════════════════════

_ANCHORS_MAP = {
    "GREETING": [
        "xin chào", "chào bạn", "hello", "hi", "chào buổi sáng", 
        "chào sếp", "xin chào tất cả", "chào mọi người", "alo"
    ],
    "TIME_QUERY": [
        "bây giờ là mấy giờ", 
        "hôm nay là ngày mấy", 
        "hôm nay thứ mấy", 
        "đồng hồ điểm mấy giờ rồi",
        "thời gian hiện tại",
        "tháng này là tháng mấy",
        "năm nay là năm nào"
    ],
    "OS_YOUTUBE": [
        "mở youtube", 
        "phát bài nhạc", 
        "bật video trên youtube", 
        "cho nghe bài hát",
        "mở bài hát lên"
    ],
    "OS_ZALO": ["mở zalo", "vào ứng dụng zalo", "khởi động zalo"],
    "OS_APP": [
        "mở ứng dụng", "bật phần mềm", "khởi động ứng dụng", 
        "mở app", "khởi chạy phần mềm", "mở word", "mở excel", 
        "mở chrome", "mở notepad", "mở vscode"
    ],
    "OS_EXPLORER": ["mở thư mục", "mở file explorer", "vào thư mục hiện tại"],
    "OS_WEBSITE": [
        "mở trang web", "vào website", "truy cập trang", "vào mạng",
        "mở facebook", "vào trang facebook", "truy cập vnexpress",
        "mở trang google docs", "vào dantri", "mở github"
    ],
    "OBSIDIAN_SAVE": [
        "lưu vào ghi chú", 
        "nhớ nội dung này lại", 
        "ghi vào sổ tay", 
        "lưu thông tin này vào não",
        "hãy ghi nhớ rằng",
        "lưu câu bạn vừa nói",
        "ghi nhớ thông tin vừa rồi"
    ],
    "FORCE_WEB": [
        "tìm trên mạng", 
        "tra google thử xem", 
        "bỏ qua rag tìm mạng đi", 
        "tra cứu internet",
        "tìm kiếm thông tin trên google"
    ],
    "EXPORT_DOCX": [
        "xuất báo cáo word", 
        "tạo file docx", 
        "lưu thành file word",
        "tổng hợp thành báo cáo word"
    ],
    "NINJA_COPY": ["copy lại câu trả lời", "sao chép câu vừa rồi", "sao chép lại text"],
    "NINJA_TOAST": ["hiện chữ lên", "bật thông báo text", "hiện text lên màn hình"],
    "NINJA_REPEAT": ["nói lại đi", "đọc lại xem nào", "nhắc lại câu vừa rồi", "nghe chưa rõ đọc lại đi"],
    "SMALL_TALK": [
        "thời tiết hôm nay", "hôm nay thế nào", "tỷ giá usd", 
        "giá vàng", "bạn thấy sao", "tóm tắt nhanh tin tức",
        "dịch câu này", "kể chuyện cười"
    ]
}

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class SemanticInterceptor:
    def __init__(self, embed_func: Callable[[str], List[float]]):
        """
        Khởi tạo Semantic Interceptor, nhận hàm nhúng vector từ QdrantManager
        để tái sử dụng e5-base, tránh tràn RAM.
        """
        self.embed_func = embed_func
        self._anchor_vectors: List[Tuple[str, List[float]]] = []
        self._is_ready = False
        
        logger.info("[SemanticInterceptor] Đang mã hóa tập Anchors (Zero-Cost)...")
        # Khởi chạy luồng nền để mã hóa anchors, không làm block quá trình khởi động
        threading.Thread(target=self._init_anchors, daemon=True).start()

    def _init_anchors(self):
        for intent, phrases in _ANCHORS_MAP.items():
            for phrase in phrases:
                vec = self.embed_func(phrase)
                self._anchor_vectors.append((intent, vec))
        self._is_ready = True
        logger.info(f"[SemanticInterceptor] Đã mã hóa xong {len(self._anchor_vectors)} neo ngữ nghĩa.")

    def _filter_whisper_hallucination(self, text: str) -> bool:
        hallucinations = ["cảm ơn các bạn", "xin chào các bạn", "subtitles by", "amara.org", "thanks for watching", "hẹn gặp lại", "chúc một ngày tốt lành", "nhớ đăng ký kênh"]
        lower_text = text.lower().strip()
        
        # 1. Lọc theo danh sách đen (ngắn gọn)
        if len(text.split()) < 10:
            for h in hallucinations:
                if h in lower_text:
                    logger.info(f"[SemanticInterceptor] Đã chặn Whisper Hallucination (Blacklist): {text[:50]}")
                    return True
                    
        # 2. Lọc theo mẫu từ lặp lại (ví dụ: "chào chào chào", "biết biết biết")
        words = lower_text.split()
        if len(words) >= 3:
            # Kiểm tra xem có 3 từ liên tiếp giống nhau không
            for i in range(len(words) - 2):
                if words[i] == words[i+1] == words[i+2]:
                    logger.info(f"[SemanticInterceptor] Đã chặn Whisper Hallucination (Repetition): {text[:50]}")
                    return True
                    
        return False

    def intercept(self, user_input: str, vault_path: str = "", last_response: str = "") -> Tuple[Optional[Any], Optional[str]]:
        text = user_input.strip()
        if not text or not self._is_ready:
            return None, None
            
        if self._filter_whisper_hallucination(text):
            return None, None

        # 1. Tính toán Vector cho User Input
        user_vec = self.embed_func(text)
        
        # 2. So khớp với tập Anchors (Tìm max Cosine Similarity)
        best_intent = None
        best_score = -1.0
        
        for intent, anchor_vec in self._anchor_vectors:
            score = cosine_similarity(user_vec, anchor_vec)
            if score > best_score:
                best_score = score
                best_intent = intent

        # [Tuning Feature] In ra màn hình để sếp dễ vặn núm THRESHOLD
        logger.info(f"[Semantic Tuning] '{text[:50]}' -> Intent: {best_intent} | Điểm Cosine: {best_score:.4f} | Threshold: {THRESHOLD}")

        # 3. Ra quyết định dựa trên Threshold
        if best_score < THRESHOLD:
            # Fallback mặc định là research_query
            return {"intent": "research_query", "query": text}, "router"
            
        return self._execute_intent(best_intent, text, vault_path, last_response)

    def _extract_payload(self, text: str, start_words: List[str]) -> str:
        """Hàm rút gọn payload thông minh dùng Regex để cắt từ khóa ở ĐẦU câu."""
        lower_text = text.lower().strip()
        # Tạo pattern từ danh sách từ khóa, ví dụ: ^(hãy|bạn hãy|mở|tìm|cho nghe)\s+
        pattern = r"^(?:bạn hãy|hãy|bạn|làm ơn)?\s*(?:" + "|".join(start_words) + r")\s*(?:rằng|là|nội dung|:)?\s*(.*)"
        match = re.search(pattern, lower_text, re.IGNORECASE)
        if match and match.group(1).strip():
            return match.group(1).strip()
        return text.strip()

    def _execute_intent(self, intent: str, text: str, vault_path: str, last_response: str) -> Tuple[Optional[Any], Optional[str]]:
        now = datetime.now()
        weekday = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"][now.weekday()]

        if intent == "GREETING":
            return "Chào sếp! Hệ thống luôn sẵn sàng hỗ trợ, sếp cần giúp gì ạ?", "fast"

        elif intent == "TIME_QUERY":
            # Xử lý nhanh ngày giờ
            if "năm" in text.lower():
                return f"Năm nay là năm {now.year}.", "fast"
            if "tháng" in text.lower():
                return f"Bây giờ là tháng {now.month} năm {now.year}.", "fast"
            if "ngày" in text.lower() or "thứ" in text.lower():
                return f"Hôm nay là {weekday}, ngày {now.strftime('%d/%m/%Y')}.", "fast"
            return f"Bây giờ là {now.strftime('%H:%M')} phút.", "fast"

        elif intent == "OS_YOUTUBE":
            payload = self._extract_payload(text, ["mở", "bật", "tìm", "phát", "youtube", "bài nhạc", "bài hát", "video", "cho nghe", "hãy", "giúp tôi", "nhờ bạn"])
            if not payload: payload = text
            self._play_youtube_async(payload)
            return f"Đang tìm và phát trên Youtube: {payload}", "ninja"
            
        elif intent == "OS_WEBSITE":
            domain = self._extract_payload(text, ["mở trang web", "vào trang web", "truy cập website", "truy cập trang", "vào trang", "vào mạng", "mở trang", "vào", "mở", "truy cập", "lướt"])
            if not domain: domain = text
            # Sử dụng DuckDuckGo "I'm Feeling Lucky" (!ducky) để tự động chuyển hướng đến trang đích
            ducky_url = f"https://duckduckgo.com/?q=!ducky+{urllib.parse.quote(domain)}"
            os.startfile(ducky_url)
            return f"Đã mở trang web: {domain}", "ninja"
            
        elif intent == "OS_ZALO":
            os.startfile("zalo:")
            return "Đã mở Zalo.", "ninja"
            
        elif intent == "OS_APP":
            app = self._extract_payload(text, ["mở ứng dụng", "khởi động phần mềm", "khởi động ứng dụng", "bật phần mềm", "khởi chạy phần mềm", "mở app", "bật app", "mở", "bật", "khởi động", "khởi chạy"])
            if not app: app = text
            # Dùng lệnh start của Windows để mở các app có trong PATH (notepad, winword, chrome...)
            subprocess.Popen(f"start {app}", shell=True)
            return f"Đã gửi lệnh khởi chạy ứng dụng: {app}", "ninja"
            
        elif intent == "OS_EXPLORER":
            subprocess.Popen("explorer .", shell=True)
            return "Đã mở File Explorer.", "ninja"

        elif intent == "OBSIDIAN_SAVE":
            if not vault_path: return "Lỗi: Không tìm thấy đường dẫn Vault.", "ninja"
            
            # Xử lý trường hợp sếp bảo "lưu câu bạn vừa nói"
            if "bạn vừa nói" in text.lower() or "thông tin vừa rồi" in text.lower() or "câu vừa rồi" in text.lower():
                payload = last_response if last_response else "Không có câu trả lời nào trước đó để lưu."
            else:
                payload = self._extract_payload(text, ["lưu vào ghi chú", "nhớ nội dung này", "ghi vào sổ tay", "lưu thông tin", "ghi nhớ", "lưu", "nhớ"])
                if not payload: payload = text
            
            memory_file = os.path.join(vault_path, OBSIDIAN_MEMORY_FILE)
            try:
                os.makedirs(os.path.dirname(memory_file), exist_ok=True)
                ts = now.strftime("%d/%m/%Y %H:%M")
                with open(memory_file, "a", encoding="utf-8") as f:
                    f.write(f"\n- [{ts}]: {payload}")
                return f"Đã ghi nhớ vào Obsidian: {payload}", "ninja"
            except Exception as e:
                return f"Lỗi ghi Obsidian: {e}", "ninja"

        elif intent == "FORCE_WEB":
            payload = self._extract_payload(text, ["hãy", "tìm trên mạng", "tra google", "bỏ qua rag", "tra cứu", "internet", "thử xem", "tìm kiếm"])
            if not payload: payload = text
            return {"intent": "daily_task", "query": payload}, "router"

        elif intent == "SMALL_TALK":
            return {"intent": "daily_task", "query": text}, "router"

        elif intent == "EXPORT_DOCX":
            payload = self._extract_payload(text, ["hãy", "xuất", "báo cáo", "word", "docx", "tạo file", "lưu thành", "tổng hợp"])
            if not payload: payload = "Báo cáo chung"
            return {"intent": "EXPORT_DOCX", "topic": payload, "query": text}, "router"

        elif intent == "NINJA_COPY":
            if last_response:
                try:
                    import pyperclip
                    pyperclip.copy(last_response)
                    return "Đã sao chép câu trả lời vào bộ nhớ tạm.", "fast"
                except ImportError:
                    return "Lỗi: Chưa cài thư viện pyperclip.", "fast"
            return "Chưa có câu trả lời nào để copy.", "fast"

        elif intent == "NINJA_TOAST":
            if last_response:
                try:
                    from win11toast import toast
                    toast("Digital Scholar", last_response[:200], duration="long")
                except ImportError:
                    logger.warning("[Interceptor] win11toast chua cai, bo qua toast.")
                except Exception as e:
                    logger.warning("[Interceptor] Loi hien thi toast: %s", e)
            return "Đã hiển thị thông báo góc màn hình.", "fast"

        elif intent == "NINJA_REPEAT":
            return "REPEAT_LAST_VOICE", "ninja"

        return None, None

    # ══════════════════════════════════════════════════════════════════════════════
    #  HELPER YOUTUBE SEARCH
    # ══════════════════════════════════════════════════════════════════════════════
    def _play_youtube_async(self, query: str):
        def _worker():
            try:
                encoded = urllib.parse.quote(query)
                req = urllib.request.Request(
                    f"https://www.youtube.com/results?search_query={encoded}",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                m = re.search(r'var ytInitialData = (\{.+?\});</script>', html, re.DOTALL)
                if m:
                    data = json.loads(m.group(1))
                    contents = data["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"]
                    for item in contents:
                        if "videoRenderer" in item:
                            vid = item["videoRenderer"]["videoId"]
                            webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
                            return
            except Exception as e:
                logger.warning("[Interceptor] Loi tim video YouTube: %s", e)
            # Fallback
            webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}")
        threading.Thread(target=_worker, daemon=True, name="YouTubeAutoPlay").start()
