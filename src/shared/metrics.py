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
    
    # Trace Tree Events
    trace_events: list = field(default_factory=list)

    def add_trace_event(self, stage: str, ms: float, **kwargs):
        event = {"stage": stage, "ms": ms}
        event.update(kwargs)
        self.trace_events.append(event)
        
    def print_trace_tree(self):
        print("\n=== [DEV MODE] TRACE TREE ===")
        for event in self.trace_events:
            stage = event.get("stage", "unknown").upper()
            ms = event.get("ms", 0.0)
            details = ", ".join(f"{k}={v}" for k, v in event.items() if k not in ["stage", "ms"])
            # Vẽ một timeline giả lập (1 block = 10ms, max 20 blocks)
            blocks = int(ms / 10)
            blocks = min(blocks, 20)
            bar = "■" * blocks
            print(f"{stage:<15} | {ms:>6.1f}ms | {bar:<20} | {details}")
        print("=============================\n")

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
def timed(metrics: PipelineMetrics, field_name: str, add_trace: bool = True, **trace_kwargs):
    t0 = time.perf_counter()
    yield
    elapsed = (time.perf_counter() - t0) * 1000
    setattr(metrics, field_name, round(elapsed, 2))
    if add_trace:
        metrics.add_trace_event(stage=field_name.replace('_ms', ''), ms=round(elapsed, 2), **trace_kwargs)
