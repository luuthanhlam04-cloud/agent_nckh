import os
import logging
from collections import deque

logger = logging.getLogger("ConversationMemory")

SLIDING_WINDOW_SIZE = 5

class ConversationMemory:
    """
    Quản lý bộ nhớ ngắn hạn hội thoại trên RAM bằng cơ chế Cửa sổ trượt.

    Spec (last agent.md Bước 7.1):
      "Duy trì mảng Dictionary chứa đúng lịch sử 5 cặp chat gần nhất.
       Khi xuất hiện câu chat thứ 6, câu thứ 1 tự động bị Pop/Delete khỏi RAM."

    Lý do dùng deque(maxlen=N):
      - Python tự động pop phần tử cũ nhất khi deque đầy.
      - Không cần viết thêm logic xóa thủ công.
      - Thread-safe cho thao tác append/pop đơn.
    """

    def __init__(self, max_size: int = SLIDING_WINDOW_SIZE):
        self._window: deque = deque(maxlen=max_size)
        self.last_response: str = ""  # Lưu câu trả lời cuối để phục vụ lệnh "copy câu vừa rồi"

    def add(self, user_input: str, agent_response: str):
        """Thêm một cặp Q&A mới vào cửa sổ trượt."""
        self._window.append({
            "role_user": user_input,
            "role_agent": agent_response,
        })
        self.last_response = agent_response

    def get_context_string(self) -> str:
        """
        Kết xuất lịch sử hội thoại thành chuỗi văn bản để nhúng vào prompt.
        """
        if not self._window:
            return ""
        lines = ["=== Lịch sử hội thoại gần nhất ==="]
        for i, pair in enumerate(self._window, 1):
            lines.append(f"[{i}] Người dùng: {pair['role_user']}")
            agent_text = pair['role_agent']
            agent_preview = agent_text[:200]
            suffix = "..." if len(agent_text) > 200 else ""
            lines.append(f"    Trợ lý: {agent_preview}{suffix}")
        return "\n".join(lines)

    def clear(self):
        """Xóa toàn bộ bộ nhớ ngắn hạn."""
        self._window.clear()
        self.last_response = ""

    def __len__(self) -> int:
        return len(self._window)
