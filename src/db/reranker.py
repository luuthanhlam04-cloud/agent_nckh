import logging
from typing import List, Dict, Any
from src.core.interfaces import IReranker
from src.shared.config import VOYAGE_API_KEY
from src.shared.rag_config import get_rag_config

logger = logging.getLogger("Reranker")

class NoOpReranker(IReranker):
    """
    Identity pass-through reranker. Không thay đổi thứ tự, chỉ thêm 'rerank_score' = score gốc.
    """
    def warmup(self) -> None:
        pass

    def rerank(self, query: str, chunks: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        for chunk in chunks:
            chunk['rerank_score'] = chunk.get('score', 0.0)
        return chunks[:top_k]

class VoyageReranker(IReranker):
    """
    Sử dụng Voyage AI API để rerank chunks.
    """
    def __init__(self, model: str = "voyage-rerank-2"):
        if not VOYAGE_API_KEY:
            logger.warning("[VoyageReranker] VOYAGE_API_KEY chưa được set. Fallback to NoOpReranker.")
            self.fallback = True
        else:
            self.fallback = False
            import voyageai
            import voyageai.error
            self.voyageai = voyageai
            self.client = voyageai.Client(api_key=VOYAGE_API_KEY)
            self.model = model

    def warmup(self) -> None:
        if not self.fallback:
            logger.info(f"[VoyageReranker] Warming up (Reranker)...")
            # VoyageAI SDK does not have a explicit ping, but auth is validated on creation.

    def rerank(self, query: str, chunks: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        if not chunks:
            return []
            
        if self.fallback:
            logger.debug("[VoyageReranker] Chạy ở chế độ fallback.")
            for chunk in chunks:
                chunk['rerank_score'] = chunk.get('score', 0.0)
            return chunks[:top_k]

        texts = [chunk.get('text', '') for chunk in chunks]
        
        try:
            import voyageai
            reranking = self.client.rerank(
                query=query,
                documents=texts,
                model=self.model,
                top_k=top_k
            )
            
            # Kết quả reranking trả về danh sách các RerankingResult
            # Mỗi result có `index` (vị trí trong mảng documents gốc), `relevance_score`
            reranked_chunks = []
            for r in reranking.results:
                original_chunk = chunks[r.index].copy()
                original_chunk['rerank_score'] = r.relevance_score
                reranked_chunks.append(original_chunk)
                
            return reranked_chunks
            
        except voyageai.error.AuthenticationError as e:
            # API key sai -> Báo lỗi rành mạch thay vì nuốt
            logger.error(f"[VoyageReranker] Sai API Key hoặc hết quyền truy cập: {e}")
            raise
        except (voyageai.error.Timeout, voyageai.error.APIConnectionError, voyageai.error.ServiceUnavailableError, voyageai.error.RateLimitError) as e:
            # Lỗi mạng / timeout / rate limit -> Fallback an toàn
            logger.warning(f"[VoyageReranker] Lỗi mạng hoặc Timeout từ Voyage: {e}. Fallback to NoOpReranker.")
            for chunk in chunks:
                chunk['rerank_score'] = chunk.get('score', 0.0)
            return chunks[:top_k]
        except voyageai.error.VoyageError as e:
            # Các lỗi API khác từ phía Voyage
            logger.warning(f"[VoyageReranker] Lỗi API từ Voyage: {e}. Fallback to NoOpReranker.")
            for chunk in chunks:
                chunk['rerank_score'] = chunk.get('score', 0.0)
            return chunks[:top_k]
        # Bỏ except Exception: để lỗi lập trình (TypeError, KeyError, v.v.) sẽ tự crash để developer debug

def get_reranker() -> IReranker:
    config = get_rag_config()
    if not config.reranker.enabled:
        return NoOpReranker()
        
    provider = config.reranker.provider.lower()
    if provider == "voyage":
        if config.dev_mode:
            import voyageai
            return VoyageReranker()
        else:
            try:
                import voyageai
                return VoyageReranker()
            except ImportError as e:
                logger.warning(f"[Reranker] Không thể import voyageai: {e}. Fallback to NoOpReranker.")
                return NoOpReranker()
    else:
        logger.warning(f"[Reranker] Provider '{provider}' chưa được support. Dùng NoOpReranker.")
        return NoOpReranker()
