from abc import ABC, abstractmethod
from typing import Generator, List, Dict, Any, Optional


class IKnowledgeStore(ABC):
    """
    Interface cho vector/graph knowledge stores.
    Implementations: QdrantManager, Neo4jManager.
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
    Implementations: GeminiLLMClient, OpenRouterLLMClient.
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
    Implementations: PDFParser, PPTXParser.
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


class IMemoryStore(ABC):
    """
    Interface cho memory persistence layer.
    Implementations: SQLiteMemoryStore.
    Future: JsonMemoryStore, PostgresMemoryStore, DuckDBMemoryStore.

    Tuân thủ DIP: MemoryConsolidator và SemanticInterceptor
    phụ thuộc vào interface này, không phụ thuộc vào SQLite cụ thể.
    """

    @abstractmethod
    def save_daily_summary(self, date_str: str, content: str) -> None:
        """Lưu/cập nhật bản tóm tắt ngày (INSERT OR REPLACE by date)."""
        pass

    @abstractmethod
    def save_quick_note(self, content: str) -> None:
        """Lưu ghi chú nhanh từ lệnh người dùng (MEMORY_SAVE intent)."""
        pass

    @abstractmethod
    def save_memory(self, memory_type: str, content: str) -> None:
        """
        Lưu một memory entry vào bảng memories.
        memory_type: 'fact', 'concept', 'preference', v.v.
        Dự phòng cho semantic memory sau này (embedding optional).
        """
        pass

    @abstractmethod
    def get_recent_summaries(self, n: int = 7) -> List[Dict[str, Any]]:
        """Lấy n bản tóm tắt gần nhất (cho context injection)."""
        pass

    @abstractmethod
    def get_recent_notes(self, n: int = 20) -> List[Dict[str, Any]]:
        """Lấy n ghi chú nhanh gần nhất."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Đóng kết nối database an toàn."""
        pass


class ISTTProvider(ABC):
    """
    Interface cho Speech-to-Text providers.
    Implementations: GeminiLiveSTT, GeminiSTT (batch fallback).
    Future: WhisperSTT, AzureSTT.

    Thiết kế streaming-first:
      start()          → khởi tạo session/stream
      push(chunk)      → gửi audio chunk liên tục
      stop()           → kết thúc stream, flush
      get_transcript() → lấy kết quả cuối cùng

    Lưu ý: Các implementation batch (GeminiSTT cũ) có thể
    buffer toàn bộ audio trong push() rồi gửi 1 lần khi stop().
    Interface đảm bảo khả năng thay thế linh hoạt.
    """

    @abstractmethod
    def start(self) -> None:
        """Khởi tạo session ghi âm / kết nối stream."""
        pass

    @abstractmethod
    def push(self, chunk: bytes) -> None:
        """Gửi một audio chunk (PCM16, mono, 16kHz) vào stream."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Kết thúc stream, flush buffer."""
        pass

    @abstractmethod
    def get_transcript(self) -> str:
        """
        Trả về kết quả transcript cuối cùng.
        Gọi sau stop(). Blocking nếu cần đợi API phản hồi.
        """
        pass
