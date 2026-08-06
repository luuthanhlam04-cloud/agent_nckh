import os
import sys
import time
import logging
import statistics

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.hybrid_rag import HybridRAG
from src.shared.rag_config import get_rag_config
from src.shared.metrics import PipelineMetrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Benchmark")

TEST_QUERIES = [
    {
        "query": "Reinforcement Learning from Human Feedback (RLHF) hoạt động như thế nào?",
        "expected_documents": ["rlhf_paper.pdf", "instructgpt.pdf"],
    },
    {
        "query": "So sánh phương pháp DPO và RLHF",
        "expected_documents": ["dpo_research.pdf", "rlhf_paper.pdf"],
    }
]

def calculate_metrics(results, expected_documents):
    hit = False
    first_hit_rank = 0
    for idx, chunk in enumerate(results):
        source = chunk.get("source", "").lower()
        if any(doc.lower() in source for doc in expected_documents):
            hit = True
            if first_hit_rank == 0:
                first_hit_rank = idx + 1
    mrr = 1.0 / first_hit_rank if first_hit_rank > 0 else 0.0
    return int(hit), mrr

def estimate_cost(query, chunks, config):
    query_tokens = len(query) / 4
    embed_cost = (query_tokens / 1_000_000) * 0.02
    rerank_cost = 0.0
    if config.reranker.enabled:
        total_chars = sum(len(c.get("text", "")) for c in chunks) + (len(query) * len(chunks))
        rerank_tokens = total_chars / 4
        rerank_cost = (rerank_tokens / 1_000_000) * 0.30
    return embed_cost, rerank_cost

def run_benchmark():
    config = get_rag_config()
    logger.info(f"--- BẮT ĐẦU BENCHMARK ---")
    
    # 1. Khởi tạo
    t0 = time.perf_counter()
    rag = HybridRAG()
    logger.info(f"Khởi tạo hệ thống (chưa tải model) mất {time.perf_counter() - t0:.2f}s")
    
    # 2. Hard Assertions
    assert rag.qdrant.embedding.model_name is not None
    logger.info(f"Hard Assertion Passed: Provider={config.embedding.provider}, Model={rag.qdrant.embedding.model_name}")
    
    # 3. Explicit Warmup
    logger.info("--- WARMUP PHASE ---")
    t_warm = time.perf_counter()
    rag.qdrant.ping()
    rag.reranker.warmup()
    logger.info(f"Hoàn thành WARMUP trong {time.perf_counter() - t_warm:.2f}s")
    
    # 4. Benchmark
    logger.info("--- BẮT ĐẦU ĐO ĐẠC ---")
    
    metrics_log = {
        "qdrant_ms": [],
        "graph_ms": [],
        "rerank_ms": [],
        "latency_ms": []
    }
    
    total_mrr = 0.0
    total_hits = 0
    total_cost = 0.0
    
    for i, test_case in enumerate(TEST_QUERIES):
        query = test_case["query"]
        expected_docs = test_case["expected_documents"]
        
        logger.info(f"\n[Query {i+1}] '{query}'")
        metrics = PipelineMetrics(query=query)
        
        t_start = time.perf_counter()
        results = rag.retrieve_context(query, top_k=config.retrieval.top_k, metrics=metrics)
        latency = (time.perf_counter() - t_start) * 1000
        
        rerank_ms = 0.0
        qdrant_ms = 0.0
        graph_ms = 0.0
        
        for event in metrics.trace_events:
            stage = event.get("stage")
            ms = event.get("ms", 0.0)
            if stage == "qdrant":
                qdrant_ms = ms
            elif stage == "rerank":
                rerank_ms = ms
            elif stage == "neo4j":
                graph_ms = ms
                
        # Ghi nhận metric
        metrics_log["latency_ms"].append(latency)
        metrics_log["qdrant_ms"].append(qdrant_ms)
        metrics_log["graph_ms"].append(graph_ms)
        metrics_log["rerank_ms"].append(rerank_ms)
        
        hit, mrr = calculate_metrics(results, expected_docs)
        total_hits += hit
        total_mrr += mrr
        
        embed_cost, rerank_cost = estimate_cost(query, results, config)
        total_cost += embed_cost + rerank_cost
        
        logger.info(f"  -> Hit: {hit} | MRR: {mrr:.2f} | Latency: {latency:.1f}ms")
        
    # 5. Phân tích Micro-Profiler
    n = len(TEST_QUERIES)
    logger.info(f"\n=== BẢNG PHÂN TÍCH HIỆU NĂNG ({n} queries) ===")
    
    def print_stats(name, data):
        if not data:
            return
        avg = statistics.mean(data)
        # Note: quantiles works on n-1 points, n=100 means 99 percentiles (0-98). P95 is index 94.
        p95 = statistics.quantiles(data, n=100)[94] if len(data) > 1 else avg
        std = statistics.stdev(data) if len(data) > 1 else 0.0
        min_v = min(data)
        max_v = max(data)
        logger.info(f"{name.ljust(15)} | Avg: {avg:6.1f} | P95: {p95:6.1f} | Std: {std:6.1f} | Min: {min_v:6.1f} | Max: {max_v:6.1f}")
        
    logger.info("Stage           | Avg    | P95    | Std    | Min    | Max")
    logger.info("-" * 80)
    print_stats("Qdrant (+Embed)", metrics_log["qdrant_ms"])
    print_stats("Neo4j Graph", metrics_log["graph_ms"])
    print_stats("Rerank", metrics_log["rerank_ms"])
    print_stats("Total Latency", metrics_log["latency_ms"])
    
    logger.info(f"\n=== TỔNG KẾT RAG ===")
    logger.info(f"Hit Rate       : {total_hits/n:.2%}")
    logger.info(f"Avg MRR        : {total_mrr/n:.2f}")
    logger.info(f"Total Cost     : ${total_cost:.6f}")

if __name__ == "__main__":
    run_benchmark()
