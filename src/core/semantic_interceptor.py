"""
semantic_interceptor.py - Bộ Giáp Ngữ Nghĩa (Semantic Interceptor)
===================================================================
Sử dụng embedding model để phân loại ý định người dùng bằng Semantic Similarity.
Giải quyết triệt để lỗi False Negative của Regex cũ.

Refactored (SQLite Memory):
  - Xóa vault_path dependency hoàn toàn.
  - Inject IMemoryStore để lưu ghi chú nhanh (MEMORY_SAVE intent).
"""

import os
import re
import json
import math
import numpy as np
import subprocess
import webbrowser
import logging
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional, Tuple, Any, Callable, List

from src.core.interfaces import IMemoryStore

logger = logging.getLogger("SemanticInterceptor")

THRESHOLD = 0.87  # Ngưỡng Cosine Similarity để quyết định

# ══════════════════════════════════════════════════════════════════════════════
#  TẬP NEO NGỮ NGHĨA (ANCHORS)
# ══════════════════════════════════════════════════════════════════════════════

# Biến cục bộ để chứa mapping. Sẽ được nạp từ file intents.json trong __init__
_ANCHORS_MAP = {}

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class SemanticInterceptor:
    def __init__(
        self,
        embed_func: Callable[[str], List[float]],
        memory_store: Optional[IMemoryStore] = None,
    ):
        """
        Khởi tạo Semantic Interceptor.

        Args:
            embed_func   : Hàm nhúng vector (tái dùng từ QdrantManager, tránh tràn RAM).
            memory_store : IMemoryStore để lưu ghi chú nhanh (MEMORY_SAVE intent).
                           None = fallback log warning.
        """
        self.embed_func   = embed_func
        self._memory_store = memory_store
        self._anchor_vectors: List[Tuple[str, List[float]]] = []
        self._is_ready = False
        
        # Load cấu hình từ file intents.json
        global _ANCHORS_MAP
        config_path = os.path.join(os.path.dirname(__file__), "intents.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                _ANCHORS_MAP = json.load(f)
        except Exception as e:
            logger.error(f"[SemanticInterceptor] Lỗi nạp intents.json: {e}")
            _ANCHORS_MAP = {}
            
        logger.info("[SemanticInterceptor] Đang mã hóa tập Anchors (Zero-Cost)...")
        # Khởi chạy luồng nền để mã hóa anchors, không làm block quá trình khởi động
        threading.Thread(target=self._init_anchors, daemon=True).start()

    def _init_anchors(self):
        for intent, phrases in _ANCHORS_MAP.items():
            for phrase in phrases:
                vec = self.embed_func(phrase)
                self._anchor_vectors.append((intent, vec))
        
        # Build numpy matrix for fast cosine similarity
        self._anchor_matrix = np.array([v for _, v in self._anchor_vectors])
        # Normalize vectors for simple dot product == cosine similarity
        norms = np.linalg.norm(self._anchor_matrix, axis=1, keepdims=True)
        self._anchor_matrix = np.divide(self._anchor_matrix, norms, out=np.zeros_like(self._anchor_matrix), where=norms!=0)
        
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

    def intercept(self, user_input: str, last_response: str = "") -> Tuple[Optional[Any], Optional[str]]:
        text = user_input.strip()
        if not text or not self._is_ready:
            return None, None

        if self._filter_whisper_hallucination(text):
            return None, None

        # 1. Tính toán Vector cho User Input
        user_vec  = np.array(self.embed_func(text))
        user_norm = np.linalg.norm(user_vec)
        if user_norm > 0:
            user_vec = user_vec / user_norm

        # 2. So khớp với tập Anchors (Tìm max Cosine Similarity dùng ma trận)
        if hasattr(self, '_anchor_matrix'):
            scores     = self._anchor_matrix @ user_vec
            best_idx   = np.argmax(scores)
            best_score = float(scores[best_idx])
            best_intent = self._anchor_vectors[best_idx][0]
        else:
            best_intent = None
            best_score  = -1.0

        logger.info(
            "[Semantic Tuning] '%s' -> Intent: %s | Score: %.4f | Threshold: %s",
            text[:50], best_intent, best_score, THRESHOLD
        )

        # 3. Ra quyết định dựa trên Threshold
        if best_score < THRESHOLD:
            return {"intent": "research_query", "query": text}, "router"

        return self._execute_intent(best_intent, text, last_response)

    def _extract_payload(self, text: str, start_words: List[str]) -> str:
        """Hàm rút gọn payload thông minh dùng Regex để cắt từ khóa ở ĐẦU câu."""
        lower_text = text.lower().strip()
        # Tạo pattern từ danh sách từ khóa, ví dụ: ^(hãy|bạn hãy|mở|tìm|cho nghe)\s+
        pattern = r"^(?:bạn hãy|hãy|bạn|làm ơn)?\s*(?:" + "|".join(start_words) + r")\s*(?:rằng|là|nội dung|:)?\s*(.*)"
        match = re.search(pattern, lower_text, re.IGNORECASE)
        if match and match.group(1).strip():
            return match.group(1).strip()
        return text.strip()

    def _sanitize_command(self, cmd: str) -> str:
        """Loại bỏ ký tự đặc biệt nguy hiểm để chống Command Injection."""
        return re.sub(r'[^a-zA-Z0-9\s-]', '', cmd).strip()

    def _execute_intent(self, intent: str, text: str, last_response: str) -> Tuple[Optional[Any], Optional[str]]:
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
            safe_app = self._sanitize_command(app)
            if safe_app:
                subprocess.Popen(f"start {safe_app}", shell=True)
                return f"Đã gửi lệnh khởi chạy ứng dụng: {safe_app}", "ninja"
            return "Tên ứng dụng không hợp lệ.", "ninja"
            
        elif intent == "OS_EXPLORER":
            subprocess.Popen("explorer .", shell=True)
            return "Đã mở File Explorer.", "ninja"

        elif intent == "OBSIDIAN_SAVE":
            # Xử lý trường hợp sếp bảo "lưu câu bạn vừa nói"
            if "bạn vừa nói" in text.lower() or "thông tin vừa rồi" in text.lower() or "câu vừa rồi" in text.lower():
                payload = last_response if last_response else "Không có câu trả lời nào trước đó để lưu."
            else:
                payload = self._extract_payload(text, ["lưu vào ghi chú", "nhớ nội dung này", "ghi vào sổ tay", "lưu thông tin", "ghi nhớ", "lưu", "nhớ"])
                if not payload:
                    payload = text

            if self._memory_store:
                try:
                    self._memory_store.save_quick_note(payload)
                    return f"Đã ghi nhớ: {payload[:80]}", "ninja"
                except Exception as e:
                    logger.error("[Interceptor] Lỗi lưu ghi chú vào SQLite: %s", e)
                    return f"Lỗi lưu ghi chú: {e}", "ninja"
            else:
                logger.warning("[Interceptor] memory_store chưa được inject. Bỏ qua MEMORY_SAVE.")
                return "Hệ thống chưa sẵn sàng lưu ghi chú.", "ninja"

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
                import yt_dlp
                ydl_opts = {
                    'default_search': 'ytsearch',
                    'noplaylist': True,
                    'quiet': True,
                    'extract_flat': True
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"ytsearch:{query}", download=False)
                    if 'entries' in info and len(info['entries']) > 0:
                        vid = info['entries'][0]['id']
                        webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
                        return
            except ImportError:
                logger.info("[Interceptor] yt-dlp chưa được cài đặt. Kích hoạt Hybrid Fallback mở trình duyệt.")
            except Exception as e:
                logger.warning(f"[Interceptor] Lỗi lấy video YouTube qua yt-dlp: {e}")
                
            # FALLBACK: Lách Zero-Dependency
            webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}")
        threading.Thread(target=_worker, daemon=True, name="YouTubeAutoPlay").start()
