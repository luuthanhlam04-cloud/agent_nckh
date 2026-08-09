import logging
from typing import List
from src.core.interfaces import IEmbedding
from src.shared.rag_config import get_rag_config
from src.shared.config import GEMINI_API_KEY

logger = logging.getLogger("Embedding")

class LocalEmbedding(IEmbedding):
    """
    Sử dụng SentenceTransformers để tạo vector nhúng cục bộ.
    """
    def __init__(self, model_name: str = "intfloat/multilingual-e5-base"):
        self._model_name = model_name
        self._model = None
        self._dimension = 768

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def warmup(self) -> None:
        if self._model is None:
            logger.info(f"[LocalEmbedding] Warming up (Loading {self._model_name} into RAM)...")
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()

    def embed_query(self, text: str) -> List[float]:
        self.warmup()
        if "e5" in self._model_name.lower():
            text = f"query: {text}"
        return self._model.encode(text).tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        self.warmup()
        if "e5" in self._model_name.lower():
            texts = [f"passage: {t}" for t in texts]
        return self._model.encode(texts).tolist()

class GeminiEmbedding(IEmbedding):
    """
    Sử dụng Gemini API để tạo vector nhúng.
    """
    def __init__(self, model_name: str = "gemini-embedding-2"):
        """
        Khởi tạo wrapper cho Gemini Embedding.
        :param model_name: Tên model, ưu tiên gemini-embedding-2
        """
        self._model_name = model_name
        # Gemini Embedding 2 mặc định là 3072, nhưng Qdrant đang dùng 768
        self._dimension = 768
        self._client = None

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def warmup(self) -> None:
        if self._client is None:
            logger.info(f"[GeminiEmbedding] Warming up (Authenticating client for {self._model_name})...")
            from google import genai
            self._client = genai.Client(api_key=GEMINI_API_KEY)
            # Chỉ khởi tạo client chứ không call embed_content để tránh tốn quota

    def embed_query(self, text: str) -> List[float]:
        self.warmup()
        try:
            # Ép kiểu output_dimensionality = 768 để tương thích với Qdrant collection cũ
            res = self._client.models.embed_content(
                model=self._model_name,
                contents=text,
                config={"output_dimensionality": self._dimension}
            )
            return res.embeddings[0].values
        except Exception as e:
            logger.error(f"[GeminiEmbedding] Lỗi khi gọi API: {e}")
            # Trả về vector 0 nếu lỗi để hệ thống không crash (Fallback)
            return [0.0] * self._dimension

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        self.warmup()
        try:
            res = self._client.models.embed_content(
                model=self._model_name,
                contents=texts,
                config={"output_dimensionality": self._dimension}
            )
            return [e.values for e in res.embeddings]
        except Exception as e:
            logger.error(f"[GeminiEmbedding] Lỗi khi gọi API embed_documents: {e}")
            return [[0.0] * self._dimension for _ in texts]

def get_embedding() -> IEmbedding:
    config = get_rag_config()
    provider = config.embedding.provider.lower()
    
    if provider == "gemini":
        return GeminiEmbedding()
    elif provider == "local":
        return LocalEmbedding()
    else:
        logger.warning(f"[Embedding] Provider '{provider}' chưa được hỗ trợ. Fallback to LocalEmbedding.")
        return LocalEmbedding()
