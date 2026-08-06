"""
src/db/knowledge_filter.py
Bộ lọc chất lượng dữ liệu trước khi nạp vào hệ thống (Knowledge Filter).
"""
import logging
import os
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("KnowledgeFilter")

class KnowledgeFilter:
    """
    Xử lý Data Quality cho các chunk trước khi vào Qdrant.
    Tầng 1: Deterministic checks (chiều dài, rác).
    Tầng 2: Metadata normalization (chuẩn hóa tên nguồn, trang).
    """
    
    MIN_CHARS = 30
    MAX_CHARS = 3000

    @classmethod
    def filter_and_normalize(cls, chunks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """
        Lọc và chuẩn hóa chunk. Trả về danh sách chunk hợp lệ và thống kê.
        """
        valid_chunks = []
        stats = {
            "total_input": len(chunks),
            "rejected_too_short": 0,
            "rejected_too_long": 0,
            "rejected_gibberish": 0,
            "total_valid": 0
        }
        
        for chunk in chunks:
            text = chunk.get("text", "")
            if not isinstance(text, str):
                text = str(text)
            text = text.strip()
            
            # --- Tầng 1: Deterministic Check ---
            if len(text) < cls.MIN_CHARS:
                stats["rejected_too_short"] += 1
                continue
                
            if len(text) > cls.MAX_CHARS:
                stats["rejected_too_long"] += 1
                continue
                
            # Basic gibberish check (Ví dụ chuỗi quá dài không có dấu cách)
            if len(text) > 50 and " " not in text:
                stats["rejected_gibberish"] += 1
                continue
                
            # --- Tầng 2: Metadata Normalization ---
            source = chunk.get("source", "unknown")
            if not isinstance(source, str):
                source = str(source)
                
            # Chỉ lấy filename thay vì absolute path để bảo mật và thống nhất
            source = os.path.basename(source.replace("\\", "/"))
            chunk["source"] = source
            
            # Ép kiểu an toàn cho page
            try:
                chunk["page"] = int(chunk.get("page", 0))
            except (ValueError, TypeError):
                chunk["page"] = 0
                
            chunk["text"] = text
            valid_chunks.append(chunk)
            
        stats["total_valid"] = len(valid_chunks)
        if stats["total_input"] != stats["total_valid"]:
            logger.info(f"[KnowledgeFilter] Đã lọc {stats['total_input']} -> {stats['total_valid']} chunks. Bỏ: short={stats['rejected_too_short']}, long={stats['rejected_too_long']}, gibberish={stats['rejected_gibberish']}")
            
        return valid_chunks, stats
