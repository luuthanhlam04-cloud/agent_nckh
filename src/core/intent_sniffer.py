"""
src/core/intent_sniffer.py

Hybrid Intent Sniffer & Vietnamese Stopword Stripper.
Tách biệt triệt để luồng Actionable Desktop Tools (YouTube, Volume, App, System)
khỏi luồng AI Research / RAG bằng phương pháp Deterministic 3 lớp:
1. Co-occurrence Pattern Matching (Action Verbs + Target Platforms)
2. Vietnamese Spoken Filler & Stopword Stripper (loại bỏ từ đệm giọng nói)
3. Slot Confidence Gate & Graceful Fallback (tránh tìm kiếm rác)
"""

import re
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class SniffResult:
    is_intercepted: bool
    intent: Optional[str] = None
    cleaned_slot: Optional[str] = None
    raw_query: str = ""
    confidence: float = 0.0
    action_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    needs_clarification: bool = False
    clarification_prompt: Optional[str] = None


class VietnameseStopwordStripper:
    """
    Bộ lọc chuyên dụng cho văn nói tiếng Việt trong môi trường Voice Assistant.
    Loại bỏ các từ nối, từ đệm, trợ từ, đại từ xưng hô và các cấu trúc câu rườm rà.
    """

    # Danh sách từ đệm và hư từ thường gặp ở đầu câu hoặc xen giữa khi nói
    FILLERS = [
        r"^(\s*(ừm|ờ|à|ê|này|alo|xin chào|chào|bạn ơi|em ơi|agent ơi|bot ơi|nè)\b[\s,]*)+",
        r"\b(giùm|hộ|cho|tao|anh|em|tôi|mình|nhé|nha|với|đi|tí|chút|coi|xem|nghe|nào|được không|giúp)\b",
        r"\b(cái|chiếc|con|bài|video|clip|bài hát|bài gì|của|ở trên|trên)\b",
    ]

    @classmethod
    def clean_youtube_slot(cls, text: str) -> str:
        """Lọc sạch query tìm kiếm YouTube từ văn nói"""
        # Thay thế dấu chấm lửng, dấu phẩy xen giữa bằng khoảng trắng để tách từ
        cleaned = re.sub(r"[.,:;!?…\-]+", " ", text)
        cleaned = re.sub(cls.FILLERS[0], " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\b(mở|bật|phát|tìm|search|cho nghe|cho xem|xem|nghe)\s+(youtube|ytb|nhạc|video|clip|bài hát|bài)?\b",
            " ", cleaned, flags=re.IGNORECASE
        )
        cleaned = re.sub(r"\b(trên|ở)\s+(youtube|ytb)\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(youtube|ytb)\b", " ", cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(cls.FILLERS[1], " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(cls.FILLERS[2], " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(bài gì của|bài của|bài gì|bài|gì|của|ấy|đó|này)\b", " ", cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @classmethod
    def clean_app_slot(cls, text: str) -> str:
        """Lọc tên ứng dụng từ câu lệnh mở app"""
        cleaned = re.sub(cls.FILLERS[0], "", text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(
            r"^(?:bạn hãy|hãy|bạn|làm ơn)?\s*(?:mở ứng dụng|khởi động phần mềm|khởi động ứng dụng|bật phần mềm|khởi chạy phần mềm|mở app|bật app|mở|bật|khởi động|khởi chạy)\s+",
            "", cleaned, flags=re.IGNORECASE
        )
        cleaned = re.sub(cls.FILLERS[1], " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Map common friendly names to standard process names
        lowered = cleaned.lower()
        if "vs code" in lowered or "vscode" in lowered or "visual studio code" in lowered:
            return "code"
        if "chrome" in lowered:
            return "chrome"
        if "notepad" in lowered:
            return "notepad"
        return cleaned


class HybridIntentSniffer:
    """
    Sniffer 3 lớp tách lọc Intent Desktop vs Chat/Research.
    """

    def __init__(self):
        self.stripper = VietnameseStopwordStripper()

    def sniff(self, text: str) -> SniffResult:
        if not text or not text.strip():
            return SniffResult(is_intercepted=False, raw_query=text)

        norm_text = text.lower().strip()

        # ── 1. KIỂM TRA INTENT THỜI GIAN / NGÀY THÁNG ───────────────────────
        if any(p in norm_text for p in [
            "mấy giờ", "mấy giờ rồi", "bây giờ là mấy giờ", "xem giờ",
            "ngày bao nhiêu", "hôm nay ngày", "ngày mấy", "thứ mấy", "hôm nay là thứ"
        ]):
            return SniffResult(
                is_intercepted=True,
                intent="TIME_QUERY",
                action_type="get_time",
                raw_query=text,
                cleaned_slot="current_time",
                confidence=0.99
            )

        # ── 2. KIỂM TRA INTENT COPY (NINJA_COPY) ────────────────────────────
        if any(p in norm_text for p in ["copy câu vừa rồi", "sao chép câu vừa rồi", "copy câu trả lời", "sao chép lại"]):
            return SniffResult(
                is_intercepted=True,
                intent="NINJA_COPY",
                action_type="copy_last",
                raw_query=text,
                confidence=0.95
            )

        # ── 3. KIỂM TRA INTENT FORCE WEB ─────────────────────────────────────
        if any(p in norm_text for p in ["tra mạng", "tìm trên mạng", "tra google", "bỏ qua rag", "tra cứu internet", "tra mạng bắt buộc"]):
            # Bóc tách query
            payload = re.sub(r"^(?:bạn hãy|hãy)?\s*(?:tra mạng bắt buộc|tra mạng|tìm trên mạng|tra google|bỏ qua rag|tra cứu internet)\s*", "", text, flags=re.IGNORECASE).strip()
            return SniffResult(
                is_intercepted=True,
                intent="FORCE_WEB",
                action_type="force_web",
                raw_query=text,
                cleaned_slot=payload if payload else text,
                confidence=0.95
            )

        # ── 4. KIỂM TRA INTENT EXPORT DOCX ───────────────────────────────────
        if any(p in norm_text for p in ["xuất ra word", "xuất file word", "tạo file word", "lưu thành word", "xuất docx"]):
            payload = re.sub(r"^(?:bạn hãy|hãy)?\s*(?:xuất ra word|xuất file word|tạo file word|lưu thành word|xuất docx)\s*(?:báo cáo về|về)?\s*", "", text, flags=re.IGNORECASE).strip()
            return SniffResult(
                is_intercepted=True,
                intent="EXPORT_DOCX",
                action_type="export_docx",
                raw_query=text,
                cleaned_slot=payload if payload else "Báo cáo chung",
                confidence=0.95
            )

        # ── 5. KIỂM TRA INTENT YOUTUBE ───────────────────────────────────────
        has_yt_keyword = any(k in norm_text for k in ["youtube", "ytb"])
        has_music_action = any(k in norm_text for k in ["nghe nhạc", "mở bài", "bật bài", "phát bài"])
        
        if has_yt_keyword or has_music_action:
            cleaned_slot = self.stripper.clean_youtube_slot(text)
            
            # Slot Confidence Gate
            if not cleaned_slot or len(cleaned_slot) < 2:
                # Nếu chỉ là lệnh chung như "mở youtube đi" -> Mở trang chủ youtube
                if any(p in norm_text for p in ["mở youtube đi", "mở youtube", "bật youtube"]):
                    return SniffResult(
                        is_intercepted=True,
                        intent="OS_YOUTUBE",
                        action_type="youtube_home",
                        raw_query=text,
                        cleaned_slot="https://www.youtube.com",
                        confidence=0.95,
                        needs_clarification=False,
                        metadata={"target": "youtube_home"}
                    )
                # Trường hợp khác yêu cầu mở bài mà không có tên -> Fallback hỏi lại
                return SniffResult(
                    is_intercepted=True,
                    intent="OS_YOUTUBE",
                    action_type="youtube_search_clarify",
                    raw_query=text,
                    cleaned_slot="",
                    confidence=0.9,
                    needs_clarification=True,
                    clarification_prompt="Bạn muốn mở bài hát hoặc video gì trên YouTube?",
                    metadata={"target": "youtube", "status": "slot_empty"}
                )
            
            # Slot sạch sẽ -> Thực thi trực tiếp
            return SniffResult(
                is_intercepted=True,
                intent="OS_YOUTUBE",
                action_type="youtube_search",
                raw_query=text,
                cleaned_slot=cleaned_slot,
                confidence=0.95,
                needs_clarification=False,
                metadata={"target": "youtube", "query": cleaned_slot}
            )

        # ── 6. KIỂM TRA INTENT VOLUME ────────────────────────────────────────
        if any(k in norm_text for k in ["âm lượng", "volume", "tắt tiếng", "mute", "to lên", "nhỏ lại"]):
            if any(k in norm_text for k in ["tắt tiếng", "mute", "im lặng"]):
                return SniffResult(
                    is_intercepted=True,
                    intent="OS_VOLUME",
                    action_type="volume_mute",
                    raw_query=text,
                    cleaned_slot="tắt",
                    confidence=0.95
                )
            elif any(k in norm_text for k in ["tăng", "to lên", "bật to", "lớn hơn"]):
                return SniffResult(
                    is_intercepted=True,
                    intent="OS_VOLUME",
                    action_type="volume_up",
                    raw_query=text,
                    cleaned_slot="tăng",
                    confidence=0.95
                )
            elif any(k in norm_text for k in ["giảm", "nhỏ lại", "nhỏ đi", "bé lại"]):
                return SniffResult(
                    is_intercepted=True,
                    intent="OS_VOLUME",
                    action_type="volume_down",
                    raw_query=text,
                    cleaned_slot="giảm",
                    confidence=0.95
                )
            match_num = re.search(r"\b(\d{1,3})\s*(%|phần trăm)?\b", norm_text)
            if match_num:
                val = int(match_num.group(1))
                if 0 <= val <= 100:
                    return SniffResult(
                        is_intercepted=True,
                        intent="OS_VOLUME",
                        action_type="volume_set",
                        raw_query=text,
                        cleaned_slot=str(val),
                        confidence=0.98,
                        metadata={"level": val}
                    )

        # ── 7. KIỂM TRA INTENT MỞ ỨNG DỤNG (OS_APP) ─────────────────────────
        if any(k in norm_text for k in [
            "mở ứng dụng", "khởi động phần mềm", "khởi động ứng dụng", "bật phần mềm",
            "mở app", "bật app", "mở vscode", "mở vs code", "mở chrome", "mở notepad"
        ]) or re.search(r"^(?:bạn hãy|hãy|bạn)?\s*mở\s+(vs code|vscode|chrome|notepad)", norm_text):
            cleaned_app = self.stripper.clean_app_slot(text)
            if cleaned_app:
                return SniffResult(
                    is_intercepted=True,
                    intent="OS_APP",
                    action_type="open_app",
                    raw_query=text,
                    cleaned_slot=cleaned_app,
                    confidence=0.95,
                    metadata={"app": cleaned_app}
                )

        # Không thuộc intent desktop xác định -> Nhường lại cho Semantic Interceptor / RAG
        return SniffResult(
            is_intercepted=False,
            raw_query=text,
            confidence=0.0
        )
