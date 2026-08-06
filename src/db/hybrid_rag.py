"""
hybrid_rag.py - Tầng Dữ liệu Lai Kép (Hybrid Dual-Database Layer)
==================================================================
Kiến trúc:
  - QdrantManager  : Vector DB cục bộ (Embedded Rust mode, zero-Docker)
                     Chạy thẳng trên SSD NVMe, <100MB RAM, không rò rỉ bộ nhớ.
  - Neo4jManager   : Graph DB đám mây (Neo4j Aura Free Tier)
                     Đẩy đồ thị lên Cloud -> giải phóng JVM 1-2GB RAM máy local.
  - HybridRAG      : Điều phối đồng bộ chéo hai tầng:
                     Qdrant chunk_id (UUID) được bơm vào property của Node Neo4j.
                     Khi truy xuất: Neo4j tìm thực thể -> lấy chunk_id -> Qdrant trả văn bản gốc.

Thiết kế để dễ mở rộng:
  - Mỗi class hoạt động độc lập, có thể test riêng biệt.
  - Tất cả connection được đóng tường minh sau mỗi tác vụ (tránh Memory Leak).
  - Config đọc từ .env, không hardcode.
"""

import os
import uuid
import logging
import gc
from typing import Optional, List, Dict, Any

from src.shared.rag_config import get_rag_config
from src.db.reranker import get_reranker
from src.db.embeddings import get_embedding

import torch
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
)
from neo4j import GraphDatabase, Driver, exceptions as neo4j_exceptions

# ─── Logging ─────────────────────────────────────────────────────────────────
# [S2-FIX] Không gọi basicConfig ở đây — main.py đã cấu hình toàn cục.
logger = logging.getLogger("HybridRAG")

# ─── Config (đọc từ env đã được load_dotenv() trong main.py) ───────────────────
QDRANT_COLLECTION_NAME = "scholar_knowledge"
GRAPH_RESULT_SCORE_BOOST = 0.85
QDRANT_PATH = os.path.join(os.path.dirname(__file__), "../../qdrant_storage")

from src.shared.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

# ══════════════════════════════════════════════════════════════════════════════
#  TẦNG 1: QdrantManager - Vector Database Cục bộ
# ══════════════════════════════════════════════════════════════════════════════
from src.core.interfaces import IKnowledgeStore
class EmbeddingDimensionMismatch(Exception):
    def __init__(self, expected: int, actual: int, model: str):
        super().__init__(f"Kích thước vector không khớp! Collection yêu cầu {expected}, nhưng model {model} trả về {actual}.")
        self.expected = expected
        self.actual = actual
        self.model = model

class QdrantManager(IKnowledgeStore):
    """
    Quản lý Vector Database Qdrant chạy ở chế độ Embedded (Local).
    - Không cần Docker, không cần server riêng.
    - Ghi thẳng file nhị phân xuống SSD NVMe qua đường dẫn QDRANT_PATH.
    """

    def __init__(self):
        self._client: Optional[QdrantClient] = None
        self.embedding = get_embedding()

    def _get_client(self) -> QdrantClient:
        """Lazy-init client để tiết kiệm RAM khi không dùng."""
        if self._client is None:
            os.makedirs(QDRANT_PATH, exist_ok=True)
            self._client = QdrantClient(path=QDRANT_PATH)
            logger.info(f"[Qdrant] Đã kết nối Embedded tại: {QDRANT_PATH}")
            self._ensure_collection()
        return self._client

    def ping(self):
        """Khởi động/Wakup client và model (dùng cho Benchmark)"""
        self.embedding.warmup()
        if self._client is None:
            self._get_client()
        else:
            self._client.get_collections()

    def _has_dimension_mismatch(self) -> bool:
        try:
            col_info = self._client.get_collection(collection_name=QDRANT_COLLECTION_NAME)
            actual_dim = self.embedding.dimension
            expected_dim = col_info.config.params.vectors.size
            if actual_dim != expected_dim:
                raise EmbeddingDimensionMismatch(expected=expected_dim, actual=actual_dim, model=self.embedding.model_name)
            return False
        except EmbeddingDimensionMismatch as e:
            logger.error(str(e))
            return True
        except Exception:
            return False

    def _create_collection(self):
        self._client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=VectorParams(
                size=self.embedding.dimension,
                distance=Distance.COSINE,
            ),
        )

    def _backup_and_recreate(self):
        if self._client:
            self._client.close()
            self._client = None
        if os.path.exists(QDRANT_PATH):
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{QDRANT_PATH}_backup_{timestamp}"
            os.rename(QDRANT_PATH, backup_path)
            logger.warning(f"[Qdrant] Đã backup CSDL cũ ra: {backup_path}")
        os.makedirs(QDRANT_PATH, exist_ok=True)
        self._client = QdrantClient(path=QDRANT_PATH)
        self._create_collection()
        logger.info(f"[Qdrant] Đã recreate collection: '{QDRANT_COLLECTION_NAME}' với size {self.embedding.dimension}")

    def _ensure_collection(self):
        """Tạo collection nếu chưa tồn tại hoặc sai dimension."""
        existing = [c.name for c in self._client.get_collections().collections]
        if QDRANT_COLLECTION_NAME not in existing:
            self._create_collection()
            logger.info(f"[Qdrant] Đã tạo collection: '{QDRANT_COLLECTION_NAME}'")
        else:
            if self._has_dimension_mismatch():
                logger.warning(f"[Qdrant] Collection dimension mismatch. Recreating...")
                self._backup_and_recreate()
            else:
                logger.info(f"[Qdrant] Collection '{QDRANT_COLLECTION_NAME}' đã tồn tại và đúng dimension.")
    def embed_text(self, text: str) -> List[float]:
        """Chuyển đổi đoạn văn bản thành vector số học."""
        return self.embedding.embed_query(text)

    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """
        Lưu một danh sách các chunk văn bản vào Qdrant.

        Args:
            chunks: Danh sách dict với format:
                    [{"text": "...", "source": "file.pdf", "page": 1, "metadata": {...}}]

        Returns:
            Danh sách chunk_id (UUID string) đã được lưu vào Qdrant.
            ID này sẽ được đồng bộ sang Neo4j.
        """
        client = self._get_client()

        chunk_ids = []
        points = []
        
        texts_to_embed = [chunk["text"] for chunk in chunks]
        vectors = self.embedding.embed_documents(texts_to_embed)

        for i, chunk in enumerate(chunks):
            metadata = chunk.get("metadata", {})
            chunk_type = metadata.get("chunk_type", "legacy")
            chunk_id = metadata.get("chunk_id", str(uuid.uuid4()))
            parent_id = metadata.get("parent_id")

            vector = vectors[i]
            payload = {
                "chunk_type": chunk_type,
                "text": chunk["text"],
                "source": chunk.get("source", "unknown"),
                "page": chunk.get("page", 0),
                **metadata,
            }
            if parent_id:
                payload["parent_id"] = parent_id

            points.append(PointStruct(id=chunk_id, vector=vector, payload=payload))
            chunk_ids.append(chunk_id)

        # Upsert theo batch để tối ưu hiệu suất
        client.upsert(collection_name=QDRANT_COLLECTION_NAME, points=points)
        logger.info(f"[Qdrant] Đã lưu {len(points)} chunks thành công (bao gồm Parent & Child).")
        return chunk_ids

    # Đã xóa hàm _rerank (Logic cũ dùng Bi-Encoder ghép chuỗi sai nguyên lý và gây nghẽn cổ chai CPU)


    def search(self, query: str, top_k: int = 5, filter_source: Optional[str] = None) -> List[Dict]:
        """
        Tìm kiếm ngữ nghĩa (Sprint B + C):
        - B1: Tìm top-20 chunk (ưu tiên Child) bằng Cosine thô.
        - B2: Rerank top-20 xuống top_k bằng e5-base contextual similarity.
        - B3: Nếu chunk là Child, fetch Parent chunk gốc trả về cho AI.
        """
        client = self._get_client()
        vector = self.embed_text(query)

        # [Sprint B] Lọc chỉ tìm các chunk có thể chứa thông tin chi tiết (child hoặc legacy)
        conditions = [
            FieldCondition(key="chunk_type", match=MatchAny(any=["child", "legacy"]))
        ]
        if filter_source:
            conditions.append(FieldCondition(key="source", match=MatchValue(value=filter_source)))

        qdrant_filter = Filter(must=conditions)
        
        response = client.query_points(
            collection_name=QDRANT_COLLECTION_NAME,
            query=vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        
        # [Sprint C] Không dùng rerank on-the-fly sai lệch nữa. Qdrant cosine search là đủ.
        # Lấy trực tiếp top_k từ kết quả đã được Qdrant sắp xếp.
        top_candidates = response.points
        if not top_candidates:
            return []
            
        # [Sprint B] Parent Retrieval Logic
        final_results = []
        parent_ids_to_fetch = set()
        child_mapping = {}  # Lưu thông tin child để biết score và text highlight
        
        for r in top_candidates:
            pid = r.payload.get("parent_id")
            rerank_score = r.score

            if pid:
                if pid not in child_mapping:
                    parent_ids_to_fetch.add(pid)
                    child_mapping[pid] = {
                        "score": rerank_score,
                        "child_text": r.payload.get("text", "")
                    }
            else:
                # Chunk legacy, không có parent
                final_results.append({
                    "chunk_id": str(r.id),
                    "score": round(rerank_score, 4),
                    "text": r.payload.get("text", ""),
                    "source": r.payload.get("source", ""),
                    "page": r.payload.get("page", 0),
                })
                
        # Lấy Parent chunks từ DB
        if parent_ids_to_fetch:
            parents = client.retrieve(
                collection_name=QDRANT_COLLECTION_NAME,
                ids=list(parent_ids_to_fetch),
                with_payload=True
            )
            for p in parents:
                pid = str(p.id)
                child_info = child_mapping.get(pid, {})
                final_results.append({
                    "chunk_id": pid,
                    "score": round(child_info.get("score", 0.0), 4),
                    "text": p.payload.get("text", ""),  # Text gốc lớn của Parent
                    "source": p.payload.get("source", ""),
                    "page": p.payload.get("page", 0),
                    "highlight": child_info.get("child_text", "")  # Text của Child để highlight
                })
                
        # Sắp xếp lại lần cuối vì kết hợp cả legacy và parent
        final_results.sort(key=lambda x: x["score"], reverse=True)
        return final_results[:top_k]

    def get_chunks_by_ids(self, chunk_ids: List[str]) -> List[Dict]:
        """
        Lấy nội dung text của các chunk dựa trên danh sách ID.
        Được dùng trong bước 5.3 của đặc tả (Vector Dense Extraction).
        """
        client = self._get_client()
        results = client.retrieve(
            collection_name=QDRANT_COLLECTION_NAME,
            ids=chunk_ids,
            with_payload=True,
        )
        return [
            {"chunk_id": str(r.id), "text": r.payload.get("text", ""), **r.payload}
            for r in results
        ]

    def close(self):
        """Đóng kết nối và dọn RAM."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("[Qdrant] Đã đóng kết nối.")
        if self._model:
            del self._model
            self._model = None
            gc.collect()


# ══════════════════════════════════════════════════════════════════════════════
#  TẦNG 2: Neo4jManager - Graph Database Đám mây
# ══════════════════════════════════════════════════════════════════════════════
class Neo4jManager:
    """
    Quản lý Graph Database Neo4j Aura Free Tier trên đám mây.
    - Kết nối qua URI (neo4j+s://) từ file .env.
    - Mỗi Node đại diện cho một Thực thể học thuật (Concept, Author, Method, Paper).
    - Mỗi Node chứa property 'qdrant_chunk_ids' để đồng bộ chéo với Qdrant.
    - Sử dụng lược đồ tinh gọn để không chạm trần 200.000 nodes của Free Tier.
    """

    # Danh sách loại Node hợp lệ trong đồ thị (Schema cố định để dễ mở rộng)
    VALID_NODE_TYPES = {"Concept", "Paper", "Author", "Method", "Finding", "Dataset"}

    def __init__(self):
        self._driver: Optional[Driver] = None

    def _get_driver(self) -> Driver:
        """Lazy-init driver để tránh kết nối khi không cần."""
        if self._driver is None:
            # [C3-FIX] Kiểm tra cả template placeholder "diền" giống API keys,
            # tránh người dùng để nguyên template rồi hệ thống kết nối thất bại khó debug.
            neo4j_pw = NEO4J_PASSWORD
            is_placeholder = (
                not NEO4J_URI
                or not neo4j_pw
                or "diền" in NEO4J_URI.lower()
                or "diền" in neo4j_pw.lower()
            )
            if is_placeholder:
                raise ValueError(
                    "[Neo4j] Thiếu thông tin kết nối hoặc còn dùng template placeholder. "
                    "Hãy điền NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD vào file .env"
                )
            self._driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
            )
            self._driver.verify_connectivity()
            logger.info("[Neo4j] Đã kết nối thành công đến: %s", NEO4J_URI)
        return self._driver

    def upsert_node(
        self,
        node_type: str,
        name: str,
        properties: Dict[str, Any],
        qdrant_chunk_ids: Optional[List[str]] = None,
    ) -> str:
        """
        Tạo hoặc cập nhật một Node trong đồ thị tri thức.

        Args:
            node_type: Loại node ('Concept', 'Paper', 'Method', ...).
            name: Tên định danh của node (dùng làm khóa chính).
            properties: Các thuộc tính bổ sung của node.
            qdrant_chunk_ids: Danh sách chunk_id từ Qdrant để đồng bộ chéo.

        Returns:
            node_id duy nhất trong Neo4j.
        """
        if node_type not in self.VALID_NODE_TYPES:
            raise ValueError(f"[Neo4j] Node type không hợp lệ: '{node_type}'. Chỉ chấp nhận: {self.VALID_NODE_TYPES}")

        driver = self._get_driver()
        node_id = str(uuid.uuid4())
        props = {
            "node_id": node_id,
            "name": name,
            "qdrant_chunk_ids": qdrant_chunk_ids or [],
            **properties,
        }

        # MERGE: Tạo nếu chưa có, cập nhật nếu đã tồn tại (tránh node trùng lặp)
        query = f"""
        MERGE (n:{node_type} {{name: $name}})
        ON CREATE SET n += $props, n.created_at = datetime()
        ON MATCH  SET n.qdrant_chunk_ids = $chunk_ids,
                      n.updated_at = datetime()
        RETURN n.node_id AS node_id
        """
        with driver.session() as session:
            result = session.run(query, name=name, props=props, chunk_ids=qdrant_chunk_ids or [])
            record = result.single()
            actual_id = record["node_id"] if record else node_id

        logger.info(f"[Neo4j] UPSERT Node [{node_type}] '{name}' | chunk_ids: {len(qdrant_chunk_ids or [])} IDs")
        return actual_id

    def upsert_relationship(
        self,
        from_name: str,
        from_type: str,
        to_name: str,
        to_type: str,
        rel_type: str,
        properties: Optional[Dict] = None,
    ):
        """
        Tạo hoặc cập nhật một cạnh (Relationship) giữa hai Node.

        Ví dụ: (Paper)-[:USES]->(Method), (Method)-[:RELATED_TO]->(Concept)
        """
        driver = self._get_driver()
        props = properties or {}
        query = f"""
        MATCH (a:{from_type} {{name: $from_name}})
        MATCH (b:{to_type}  {{name: $to_name}})
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r += $props, r.created_at = datetime()
        ON MATCH  SET r.updated_at = datetime()
        """
        with driver.session() as session:
            session.run(query, from_name=from_name, to_name=to_name, props=props)

        logger.info(f"[Neo4j] MERGE REL [{from_type}:'{from_name}']-[:{rel_type}]->[{to_type}:'{to_name}']")


    def upsert_entities(self, entities: List[Dict[str, Any]], relationships: List[Dict[str, Any]]):
        """
        Upsert danh sách entities và relationships từ EntityExtractor.
        """
        try:
            for ent in entities:
                self.upsert_node(
                    node_type=ent.get("label", "Concept"),
                    name=ent.get("id", ""),
                    chunk_id=None
                )
            for rel in relationships:
                self.upsert_relationship(
                    from_name=rel.get("source", ""),
                    to_name=rel.get("target", ""),
                    rel_type=rel.get("type", "RELATED_TO")
                )
            logger.info(f"[Neo4j] Đã upsert {len(entities)} entities và {len(relationships)} relationships.")
        except Exception as e:
            logger.error(f"[Neo4j] Lỗi upsert_entities: {e}")

    def query_entity_chunk_ids(
        self, keyword: str, node_type: Optional[str] = None
    ) -> List[str]:
        """
        Tìm kiếm Node theo tên/keyword và trả về danh sách Qdrant chunk_id.
        Đây là bước 5.2 trong đặc tả (Graph Structural Querying).

        Args:
            keyword: Từ khóa tìm kiếm (tiếng Anh, sau khi đã dịch từ tiếng Việt).
            node_type: Loại node cần tìm (optional, để hẹp phạm vi tìm kiếm).

        Returns:
            Danh sách chunk_id để truyền vào Qdrant tìm văn bản gốc.
        """
        driver = self._get_driver()
        type_filter = f":{node_type}" if node_type else ""

        query = f"""
        MATCH (n{type_filter})
        WHERE toLower(n.name) CONTAINS toLower($keyword)
           OR toLower(n.description) CONTAINS toLower($keyword)
        RETURN n.qdrant_chunk_ids AS chunk_ids
        LIMIT 10
        """
        all_ids = []
        with driver.session() as session:
            results = session.run(query, keyword=keyword)
            for record in results:
                ids = record.get("chunk_ids", []) or []
                all_ids.extend(ids)

        # Loại bỏ ID trùng lặp, giữ thứ tự
        seen = set()
        unique_ids = [x for x in all_ids if not (x in seen or seen.add(x))]
        logger.info(f"[Neo4j] Query '{keyword}' -> {len(unique_ids)} chunk IDs.")
        return unique_ids

    def close(self):
        """Đóng kết nối ngay sau khi dùng xong để tránh giữ lock TCP."""
        if self._driver:
            self._driver.close()
            self._driver = None
            gc.collect()
            logger.info("[Neo4j] Đã đóng kết nối.")


# ══════════════════════════════════════════════════════════════════════════════
#  TẦNG 3: HybridRAG - Điều phối Đồng bộ Chéo (Cross-Sync Orchestrator)
# ══════════════════════════════════════════════════════════════════════════════
class HybridRAG:
    """
    Điều phối toàn bộ luồng dữ liệu lai giữa Qdrant và Neo4j.

    Sơ đồ đồng bộ chéo:
    ┌─────────────────────────────────────────────────────────────┐
    │  Tài liệu (PDF/PPTX)                                        │
    │        ↓                                                     │
    │  Parser → Chunks[]                                           │
    │        ↓                                                     │
    │  Qdrant.upsert_chunks() → [chunk_id_1, chunk_id_2, ...]     │
    │        ↓ (ID đồng bộ sang Neo4j)                            │
    │  Neo4j.upsert_node(qdrant_chunk_ids=[id_1, id_2, ...])      │
    │                                                              │
    │  Khi truy xuất:                                             │
    │  Neo4j.query_entity_chunk_ids("keyword") → [id_1, id_2]     │
    │  Qdrant.get_chunks_by_ids([id_1, id_2]) → [text, text]      │
    └─────────────────────────────────────────────────────────────┘
    """

    def __init__(self, qdrant: Optional["QdrantManager"] = None, neo4j: Optional["Neo4jManager"] = None):
        self.qdrant = qdrant or QdrantManager()
        self.neo4j = neo4j or Neo4jManager()
        logger.info("[HybridRAG] Khởi tạo thành công.")

    def ingest_document(
        self,
        chunks: List[Dict[str, Any]],
        entities: List[Dict[str, Any]],
        relationships: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Pipeline nạp tài liệu học thuật vào hệ thống lai (Bước 4.3 - 4.4).

        Args:
            chunks: Danh sách đoạn văn từ parser.
                    Format: [{"text": "...", "source": "...", "page": N}]
            entities: Danh sách thực thể học thuật trích xuất từ LLM.
                    Format: [{"name": "...", "type": "Concept", "description": "..."}]
            relationships: Danh sách mối quan hệ giữa các thực thể.
                    Format: [{"from": "A", "from_type": "Concept", "to": "B",
                              "to_type": "Method", "rel": "USES"}]

        Returns:
            Thống kê kết quả nạp dữ liệu.
        """
        # Bước 0: Knowledge Filter
        from src.db.knowledge_filter import KnowledgeFilter
        chunks, stats = KnowledgeFilter.filter_and_normalize(chunks)
        if not chunks:
            logger.warning("[HybridRAG] Tất cả chunks đều bị loại bỏ bởi Knowledge Filter.")
            return {"status": "failed", "reason": "Tất cả chunks không hợp lệ", "filter_stats": stats}

        # Bước 1: Lưu tất cả chunks vào Qdrant, nhận về danh sách chunk_id
        logger.info(f"[HybridRAG] Bắt đầu nạp {len(chunks)} chunks vào Qdrant...")
        chunk_ids = self.qdrant.upsert_chunks(chunks)

        # Bước 2: Bơm chunk_id vào từng Node tương ứng trên Neo4j (Đồng bộ chéo)
        # [BUG-6 FIX] Trước đây gắn TOÀN BỘ chunk_ids vào mọi entity → graph search trả rác.
        # Chiến lược đúng: mỗi entity nhận chunk_ids của các chunk chứa tên entity đó.
        # Nếu không map được → gắn toàn bộ (graceful fallback) để không mất dữ liệu.
        logger.info(f"[HybridRAG] Đồng bộ {len(entities)} entities lên Neo4j Cloud...")
        node_results = []
        for entity in entities:
            entity_name_lower = entity["name"].lower()
            # Lọc những chunk chứa tên entity (case-insensitive)
            relevant_ids = [
                chunk_ids[i]
                for i, c in enumerate(chunks)
                if entity_name_lower in c.get("text", "").lower()
            ]
            # Fallback: nếu không tìm thấy chunk nào → dùng toàn bộ (tài liệu nhỏ)
            assigned_ids = relevant_ids if relevant_ids else chunk_ids

            node_id = self.neo4j.upsert_node(
                node_type=entity.get("type", "Concept"),
                name=entity["name"],
                properties={"description": entity.get("description", "")},
                qdrant_chunk_ids=assigned_ids,
            )
            node_results.append(node_id)

        # Bước 3: Tạo các mối quan hệ giữa các thực thể
        if relationships:
            logger.info(f"[HybridRAG] Tạo {len(relationships)} relationships trên Neo4j...")
            for rel in relationships:
                try:
                    self.neo4j.upsert_relationship(
                        from_name=rel["from"],
                        from_type=rel.get("from_type", "Concept"),
                        to_name=rel["to"],
                        to_type=rel.get("to_type", "Concept"),
                        rel_type=rel.get("rel", "RELATED_TO"),
                        properties=rel.get("properties", {}),
                    )
                except Exception as e:
                    logger.warning(f"[HybridRAG] Bỏ qua relationship lỗi: {e}")

        summary = {
            "chunks_stored": len(chunk_ids),
            "nodes_created": len(node_results),
            "relationships_created": len(relationships) if relationships else 0,
            "chunk_ids_sample": chunk_ids[:3],  # Log 3 ID đầu để debug
            "filter_stats": stats
        }
        logger.info(f"[HybridRAG] Nạp xong! Tóm tắt: {summary}")
        return summary

    def retrieve_context(self, query: str, top_k: int = 5, metrics: Any = None) -> List[Dict]:
        """
        Luồng truy xuất lai kép theo đặc tả, sử dụng Reranker.
        """
        import time
        config = get_rag_config()
        wide_k = top_k * config.retrieval.wide_factor
        
        logger.info(f"[HybridRAG] Truy xuất ngữ cảnh (wide_k={wide_k}) cho query: '{query[:50]}...'")

        # Đường 1: Vector search trực tiếp qua Qdrant
        t0 = time.perf_counter()
        vector_results = self.qdrant.search(query, top_k=wide_k)
        qdrant_ms = (time.perf_counter() - t0) * 1000
        if metrics: metrics.add_trace_event("qdrant", qdrant_ms, chunks=len(vector_results))

        # Đường 2: Graph search qua Neo4j -> lấy chunk_id -> Qdrant
        graph_results = []
        t1 = time.perf_counter()
        try:
            graph_chunk_ids = self.neo4j.query_entity_chunk_ids(keyword=query)
            if graph_chunk_ids:
                graph_results = self.qdrant.get_chunks_by_ids(graph_chunk_ids[:wide_k])
                for r in graph_results:
                    r["score"] = r.get("score", GRAPH_RESULT_SCORE_BOOST)
                    r["source_method"] = "graph"
        except (ValueError, Exception) as e:
            logger.warning("[HybridRAG] Neo4j không khả dụng, chỉ dùng vector search: %s", e)
        neo4j_ms = (time.perf_counter() - t1) * 1000
        if metrics: metrics.add_trace_event("neo4j", neo4j_ms, chunks=len(graph_results))

        for r in vector_results:
            r["source_method"] = "vector"

        # Merge và loại bỏ trùng lặp theo chunk_id
        t2 = time.perf_counter()
        seen_ids = set()
        merged = []
        for r in graph_results + vector_results:
            cid = r.get("chunk_id", "")
            if cid not in seen_ids:
                seen_ids.add(cid)
                merged.append(r)
        
        # Ghi nhận rank ban đầu trước khi rerank
        for i, chunk in enumerate(merged):
            chunk["rank_before"] = i + 1
            
        merge_ms = (time.perf_counter() - t2) * 1000
        if metrics: metrics.add_trace_event("merge", merge_ms, chunks_before_merge=len(graph_results)+len(vector_results), unique_chunks=len(merged))

        logger.info(f"[HybridRAG] Gộp được {len(merged)} unique chunks. Chuyển qua Reranker...")
        
        t3 = time.perf_counter()
        reranker = get_reranker()
        top_results = reranker.rerank(query=query, chunks=merged, top_k=top_k)
        
        # Ghi nhận rank sau khi rerank
        for i, chunk in enumerate(top_results):
            chunk["rank_after"] = i + 1
            
        rerank_ms = (time.perf_counter() - t3) * 1000
        if metrics: metrics.add_trace_event("rerank", rerank_ms, provider=config.reranker.provider, chunks_returned=len(top_results))

        logger.info(f"[HybridRAG] Trả về {len(top_results)} chunks ngữ cảnh sau rerank.")
        return top_results

    def close(self):
        """Dọn dẹp tài nguyên sau mỗi phiên làm việc."""
        self.qdrant.close()
        self.neo4j.close()
        gc.collect()
        logger.info("[HybridRAG] Đã giải phóng toàn bộ kết nối database.")


# ─── Entry point để test nhanh module này độc lập ─────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()  # Chỉ load khi chạy file độc lập để test

    print("--- HybridRAG Quick Test ---")

    rag = HybridRAG()

    # Test data (no Neo4j needed, Qdrant local is enough to test)
    test_chunks = [
        {
            "text": "GraphRAG combines knowledge graphs and vector search for more accurate context retrieval.",
            "source": "test_paper.pdf",
            "page": 1,
        },
        {
            "text": "MiniLM-L12-v2 is a lightweight multilingual embedding model for cross-lingual semantic search.",
            "source": "test_paper.pdf",
            "page": 2,
        },
    ]

    print("\n[TEST] Saving chunks to Qdrant (local)...")
    ids = rag.qdrant.upsert_chunks(test_chunks)
    print(f"  -> Saved {len(ids)} chunks. IDs: {ids}")

    print("\n[TEST] Vector search...")
    results = rag.qdrant.search("semantic search method", top_k=2)
    for r in results:
        print(f"  Score: {r['score']} | Text: {r['text'][:60]}...")

    rag.close()
    print("\n[TEST] Done. Qdrant test successful!")
