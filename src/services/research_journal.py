"""
src/services/research_journal.py

Research Journal & Socratic Thought Partner Service.
Triết lý: Knowledge Representation & Reasoning (KR&R) cho nhà nghiên cứu.
- Ghi nhật ký học thuật ngầm (Asynchronous Research Journaling) vào Obsidian Vault.
- Bóc tách giả định ngầm (implicit assumptions) và điểm nghẽn (bottlenecks).
- Cung cấp gợi ý phản biện Socratic tức thời (Just-in-Time Socratic Injection) khi người dùng tra cứu.
"""

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.shared.config import OBSIDIAN_VAULT_PATH

logger = logging.getLogger("ResearchJournal")


class ResearchJournalService:
    """
    Quản lý nhật ký nghiên cứu học thuật trong Obsidian Vault.
    Thư mục: Obsidian_Vault/05_Research_Journal/YYYY-MM-DD.md
    """

    def __init__(self, vault_path: Optional[str] = None):
        self.vault_path = vault_path or OBSIDIAN_VAULT_PATH or os.path.abspath("Obsidian_Vault")
        self.journal_dir = os.path.join(self.vault_path, "05_Research_Journal")
        os.makedirs(self.journal_dir, exist_ok=True)
        logger.info("[ResearchJournal] Sẵn sàng tại: %s", self.journal_dir)

    def _get_today_filepath(self) -> str:
        today_str = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.journal_dir, f"{today_str}.md")

    def record_gap(
        self,
        paper_title: str,
        hypothesis_or_gap: str,
        bottleneck: Optional[str] = None,
        source_tags: Optional[List[str]] = None
    ) -> str:
        """
        Ghi nhận một điểm nghẽn hoặc lỗ hổng nghiên cứu (Research Gap) vào nhật ký.
        """
        file_path = self._get_today_filepath()
        now_str = datetime.now().strftime("%H:%M:%S")
        tags_str = " ".join([f"#{t.strip('#')}" for t in (source_tags or ["ResearchGap", "NCKH"])])

        entry = f"""
### [{now_str}] {paper_title}
- **Vấn đề / Điểm nghẽn:** {hypothesis_or_gap}
"""
        if bottleneck:
            entry += f"- **Giả định / Rủi ro:** {bottleneck}\n"
        entry += f"- **Tags:** {tags_str}\n\n---\n"

        # Nếu file chưa tồn tại, tạo header
        if not os.path.exists(file_path):
            header = f"# Nhật Ký Nghiên Cứu - {datetime.now().strftime('%d/%m/%Y')}\n\n"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(header)

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.info("[ResearchJournal] Đã ghi nhận Gap vào %s", file_path)
        return file_path

    def read_today_journal(self) -> str:
        file_path = self._get_today_filepath()
        if not os.path.exists(file_path):
            return "Hôm nay chưa có ghi chép nhật ký nghiên cứu nào."
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def generate_socratic_prompt(topic: str, context_preview: str = "") -> str:
        """
        Tạo lời gợi ý phản biện Socratic (Dialectic Thought Partner).
        Hỗ trợ nhà nghiên cứu tự mò ra điểm nghẽn thay vì AI nghĩ thay.
        """
        return (
            f"\n\n💡 **Gợi ý phản biện học thuật (Socratic Thought Partner):**\n"
            f"- Phương pháp trên có phụ thuộc vào giả định ngầm nào không (ví dụ: dữ liệu tĩnh, tài nguyên RAM/VRAM, phân phối IID)?\n"
            f"- Nếu áp dụng vào bài toán thực tế của bạn, điểm nghẽn (bottleneck) lớn nhất có thể nằm ở bước nào?"
        )

