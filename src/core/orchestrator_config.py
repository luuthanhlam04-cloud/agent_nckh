"""
src/core/orchestrator_config.py — Config-Driven Node Configuration
===================================================================
Thay thế if/else intent == "daily_task" bằng config objects.
Node không cần biết mình phục vụ Fast hay Research — chỉ nhận config.

ADR-005: Config-Driven Nodes thay vì Strategy Pattern (quá phức tạp cho scale hiện tại).
"""
from dataclasses import dataclass, field


# ─── Node Configs ──────────────────────────────────────────────────────────────

@dataclass
class RetrieveConfig:
    """
    Config cho _node_retrieve() — kiểm soát cách truy xuất ngữ cảnh.
    Node không biết Fast hay Research — chỉ đọc config này.
    """
    top_k: int = 5
    """Số chunks trả về từ Qdrant/Neo4j."""

    use_graph: bool = True
    """Có dùng Neo4j GraphRAG không (khi đã implement entity extraction)."""

    use_web_fallback: bool = True
    """Có tự động search web khi context rỗng không."""

    max_critique_rounds: int = 3
    """Số vòng tối đa Critique + Web Search trước khi force generate."""

    critique_threshold: float = 8.0
    """Điểm trung bình tối thiểu để bỏ qua web search."""


@dataclass
class GenerateConfig:
    """
    Config cho _node_generate() — kiểm soát cách sinh câu trả lời.
    """
    system_prompt: str = ""
    """System prompt sẽ được inject từ PromptBuilder — không hardcode ở đây."""

    max_tokens: int = 2048
    """Giới hạn output token."""

    temperature: float = 0.7
    """Độ sáng tạo của LLM."""

    streaming: bool = True
    """Có stream response không."""


@dataclass
class OrchestratorConfig:
    """
    Config tổng hợp cho một lần run() của ReActOrchestrator.
    Mỗi intent_type → một OrchestratorConfig preset.
    """
    retrieve: RetrieveConfig = field(default_factory=RetrieveConfig)
    generate: GenerateConfig = field(default_factory=GenerateConfig)
    use_critique: bool = True
    """Có chạy bước Critique không."""

    parallel_rag_web: bool = False
    """Có fetch RAG và Web song song (ThreadPoolExecutor) không."""

    intent_label: str = "research_query"
    """Label debug — không ảnh hưởng logic."""


# ─── Preset Configs ────────────────────────────────────────────────────────────

def _make_fast_config() -> OrchestratorConfig:
    """
    Fast-Track config cho intent daily_task.
    Đặc điểm: top_k nhỏ, không critique, không graph, song song RAG+web, output ngắn.
    """
    return OrchestratorConfig(
        retrieve=RetrieveConfig(
            top_k=3,
            use_graph=False,
            use_web_fallback=True,
            max_critique_rounds=0,  # Không critique trong fast mode
        ),
        generate=GenerateConfig(
            # system_prompt sẽ được set bởi PromptBuilder khi gọi
            max_tokens=512,
            temperature=0.7,
            streaming=True,
        ),
        use_critique=False,
        parallel_rag_web=True,   # Chạy RAG và Web song song để nhanh hơn
        intent_label="daily_task",
    )


def _make_deep_config() -> OrchestratorConfig:
    """
    Deep-Track config cho intent research_query.
    Đặc điểm: top_k lớn, critique đầy đủ, có thể dùng graph, output dài.
    """
    return OrchestratorConfig(
        retrieve=RetrieveConfig(
            top_k=5,
            use_graph=True,
            use_web_fallback=True,
            max_critique_rounds=3,
            critique_threshold=8.0,
        ),
        generate=GenerateConfig(
            max_tokens=2048,
            temperature=0.7,
            streaming=True,
        ),
        use_critique=True,
        parallel_rag_web=False,  # Sequential để critique quality
        intent_label="research_query",
    )


# ─── Exported Presets ──────────────────────────────────────────────────────────

FAST_TRACK_CONFIG: OrchestratorConfig = _make_fast_config()
DEEP_TRACK_CONFIG: OrchestratorConfig = _make_deep_config()

# Map intent string → config (mở rộng khi thêm intent mới)
INTENT_CONFIG_MAP: dict[str, OrchestratorConfig] = {
    "daily_task": FAST_TRACK_CONFIG,
    "research_query": DEEP_TRACK_CONFIG,
    # Tương lai:
    # "vision_task": VISION_CONFIG,
    # "export_task": EXPORT_CONFIG,
}


def get_config_for_intent(intent: str) -> OrchestratorConfig:
    """
    Tra cứu config từ intent string.
    Fallback về DEEP_TRACK_CONFIG cho intent không xác định.
    """
    return INTENT_CONFIG_MAP.get(intent, DEEP_TRACK_CONFIG)
