import os
import yaml
from pydantic import BaseModel
import logging

logger = logging.getLogger("RAGConfig")

class EmbeddingConfig(BaseModel):
    provider: str = "gemini"

class RerankerConfig(BaseModel):
    enabled: bool = True
    provider: str = "voyage"

class RetrievalConfig(BaseModel):
    wide_factor: int = 4
    top_k: int = 5

class ContextConfig(BaseModel):
    max_chunk_tokens: int = 20000
    prompt_version: str = "v1"

class RAGConfig(BaseModel):
    dev_mode: bool = False
    embedding: EmbeddingConfig = EmbeddingConfig()
    reranker: RerankerConfig = RerankerConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    context: ContextConfig = ContextConfig()

_config_instance = None

def get_rag_config() -> RAGConfig:
    global _config_instance
    if _config_instance is not None:
        return _config_instance

    # Đường dẫn file config/rag.yaml
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_path = os.path.join(base_dir, "config", "rag.yaml")

    if not os.path.exists(config_path):
        logger.warning(f"[RAGConfig] File {config_path} không tồn tại. Sử dụng default config.")
        _config_instance = RAGConfig()
        return _config_instance

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            
        _config_instance = RAGConfig(**data)
        logger.info(f"[RAGConfig] Loaded config từ {config_path}")
    except Exception as e:
        logger.error(f"[RAGConfig] Lỗi khi load config: {e}. Sử dụng default config.")
        _config_instance = RAGConfig()

    return _config_instance
