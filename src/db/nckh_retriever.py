from typing import List, Dict, Any
from src.core.interfaces import IRetriever, IKnowledgeStore
import logging

logger = logging.getLogger("NCKHRetriever")

class NCKHRetriever(IRetriever):
    """
    Retriever đặc thù cho đề tài NCKH.
    - Tìm kiếm vector (Qdrant) trả về Child Chunks, nhưng lấy Parent Chunk làm context.
    - Kết hợp Graph search (Neo4j) để tìm các thực thể liên quan.
    """
    def __init__(self, hybrid_rag: IKnowledgeStore):
        self.hybrid_rag = hybrid_rag

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        logger.info(f"[NCKHRetriever] Bắt đầu tìm kiếm với NCKH strategy, query='{query}', top_k={top_k}")
        
        # 1. Tìm kiếm Vector
        vector_results = self.hybrid_rag.search(query, top_k)
        
        # 2. Thay thế Child Chunk bằng Parent Chunk
        # Giả định vector_results là danh sách các dict chứa payload từ Qdrant
        final_context = []
        for res in vector_results:
            if "parent_text" in res and res["parent_text"]:
                # Dùng parent_text làm ngữ cảnh đầy đủ
                res["text"] = res["parent_text"]
            final_context.append(res)
            
        # 3. Kết hợp Graph Search (nếu Neo4j khả dụng)
        if hasattr(self.hybrid_rag, "neo4j") and self.hybrid_rag.neo4j:
            try:
                # Đơn giản hoá bằng text search hoặc keyword extraction
                # Trong thực tế, cần LLM extract keyword từ query
                pass # Graph search logic
            except Exception as e:
                logger.error(f"[NCKHRetriever] Lỗi Graph Search: {e}")
                
        return final_context
