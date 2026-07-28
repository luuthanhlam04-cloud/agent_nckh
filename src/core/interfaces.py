from abc import ABC, abstractmethod
from typing import Generator, List, Dict, Any, Optional

class IKnowledgeStore(ABC):
    """
    Interface cho vector/graph knowledge stores.
    """
    @abstractmethod
    def search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> List[str]:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class ILLMClient(ABC):
    """
    Interface cho LLM providers.
    """
    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> Generator[str, None, None]:
        pass

class IParser(ABC):
    """
    Interface cho document parsers.
    Implementations: PDFParser, PPTXParser (hiện tại) + NCKHParser (Sprint 5)
    """
    @abstractmethod
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def supported_extensions(self) -> List[str]:
        pass

class IRetriever(ABC):
    """
    Interface cho retrieval strategies.
    Implementations: HybridRAGRetriever, NCKHRetriever.
    """
    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        pass
