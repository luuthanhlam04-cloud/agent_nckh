import time
import uuid
import logging
from dataclasses import dataclass, field
from contextlib import contextmanager

_log = logging.getLogger("Metrics")

@dataclass
class PipelineMetrics:
    # Correlation IDs
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    conversation_id: str = ""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    # Query info
    query: str = ""
    intent: str = ""
    
    # Performance (ms)
    embedding_ms: float = 0.0
    qdrant_ms: float = 0.0
    neo4j_ms: float = 0.0
    critique_ms: float = 0.0
    llm_first_token_ms: float = 0.0
    llm_total_ms: float = 0.0
    tts_ms: float = 0.0
    stt_ms: float = 0.0
    
    # Quality
    chunks_retrieved: int = 0
    critique_rounds: int = 0
    critique_score: float = 0.0
    web_search_used: bool = False

    def log_summary(self):
        _log.info(
            "[Metrics] req=%s conv=%s intent=%s "
            "embed=%.0fms qdrant=%.0fms critique=%.0fms "
            "llm_ttft=%.0fms llm_total=%.0fms "
            "chunks=%d rounds=%d web=%s",
            self.request_id, self.conversation_id[:8], self.intent,
            self.embedding_ms, self.qdrant_ms, self.critique_ms,
            self.llm_first_token_ms, self.llm_total_ms,
            self.chunks_retrieved, self.critique_rounds, self.web_search_used
        )

@contextmanager
def timed(metrics: PipelineMetrics, field_name: str):
    t0 = time.perf_counter()
    yield
    elapsed = (time.perf_counter() - t0) * 1000
    setattr(metrics, field_name, round(elapsed, 2))
