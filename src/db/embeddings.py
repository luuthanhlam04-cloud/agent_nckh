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
    def __init__(self, model_name: str = "text-embedding-004"):
        self._model_name = model_name
        self._dimension = 768
        self._client = None
        if not GEMINI_API_KEY:
            logger.error("[GeminiEmbedding] GEMINI_API_KEY is missing!")

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
        response = self._client.models.embed_content(
            model=self._model_name,
            contents=text,
        )
        return response.embeddings[0].values

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        self.warmup()
        response = self._client.models.embed_content(
            model=self._model_name,
            contents=texts,
        )
        return [emb.values for emb in response.embeddings]

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
