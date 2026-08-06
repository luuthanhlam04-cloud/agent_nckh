"""
src/core/context_manager.py
Xử lý Token Budgeting và chuẩn bị PromptContext cho PromptBuilder.
"""
from typing import List, Dict, Any
import logging
from src.core.prompt_builder import PromptContext

logger = logging.getLogger("ContextManager")

class ContextManager:
    """
    Quản lý ngữ cảnh, đảm bảo không vượt quá token limit.
    """
    def __init__(self, max_tokens: int = 8000):
        self.max_tokens = max_tokens
        self.chars_per_token = 4 # Ước tính trung bình 1 token = 4 chars (tiếng Việt)

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // self.chars_per_token

    def build_context(self, 
                      user_query: str, 
                      rag_chunks: List[Dict[str, Any]], 
                      web_results: List[str], 
                      conversation_history: str = "") -> PromptContext:
        """
        Xây dựng PromptContext, cắt bớt ngữ cảnh nếu vượt quá max_tokens.
        Thứ tự ưu tiên giữ lại: Query > History > RAG > Web.
        """
        budget = self.max_tokens - self._estimate_tokens(user_query)
        
        # 1. Xử lý Lịch sử (giữ tối đa 20% budget cho history)
        history_budget = int(budget * 0.2)
        history_text = conversation_history
        if self._estimate_tokens(history_text) > history_budget:
            allowed_chars = history_budget * self.chars_per_token
            history_text = "..." + history_text[-(allowed_chars-3):]
        
        budget -= self._estimate_tokens(history_text)
        
        # 2. Xử lý RAG chunks
        rag_budget = int(budget * 0.7) if web_results else budget
        
        formatted_rag_chunks = []
        current_rag_tokens = 0
        doc_sources = set()
        
        for i, c in enumerate(rag_chunks):
            source = c.get('source', 'unknown')
            page = c.get('page', 0)
            text = c.get('text', '')
            chunk_str = f"[Tài liệu {i+1} | {source} trang {page}]\n{text}"
            
            chunk_tokens = self._estimate_tokens(chunk_str)
            if current_rag_tokens + chunk_tokens > rag_budget:
                logger.info(f"[ContextManager] Đạt giới hạn token cho RAG ({current_rag_tokens}/{rag_budget}). Loại bỏ {len(rag_chunks) - i} chunks cuối.")
                break
                
            formatted_rag_chunks.append(chunk_str)
            current_rag_tokens += chunk_tokens
            if source:
                doc_sources.add(source)
                
        rag_context = "\n\n".join(formatted_rag_chunks)
        budget -= current_rag_tokens
        
        # 3. Xử lý Web results
        formatted_web_chunks = []
        current_web_tokens = 0
        
        # Đảo ngược web_results vì kết quả mới nhất thường nằm ở cuối (như logic cũ trong orchestrator)
        for i, w in enumerate(reversed(web_results)):
            chunk_str = f"[Kết quả web {i+1}]\n{w}"
            chunk_tokens = self._estimate_tokens(chunk_str)
            if current_web_tokens + chunk_tokens > budget:
                logger.info(f"[ContextManager] Đạt giới hạn token cho Web ({current_web_tokens}/{budget}).")
                break
                
            formatted_web_chunks.insert(0, chunk_str) # Chèn lại vào đầu để giữ đúng thứ tự
            current_web_tokens += chunk_tokens
            
        web_context = "\n\n".join(formatted_web_chunks)
        
        return PromptContext(
            user_query=user_query,
            rag_context=rag_context,
            web_context=web_context,
            conversation_history=history_text,
            doc_sources=list(doc_sources)
        )
