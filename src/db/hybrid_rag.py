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
import torch
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)
from neo4j import GraphDatabase, Driver, exceptions as neo4j_exceptions

# ─── Logging ─────────────────────────────────────────────────────────────────
# [S2-FIX] Không gọi basicConfig ở đây — main.py đã cấu hình toàn cục.
logger = logging.getLogger("HybridRAG")

# ─── Tải biến môi trường ───────────────────────────────────────────────────────
load_dotenv()

# ─── Hằng số cấu hình ─────────────────────────────────────────────────────────
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-base"
QDRANT_COLLECTION_NAME = "scholar_knowledge"
QDRANT_VECTOR_SIZE = 768  # Kích thước vector của gte-multilingual-base
QDRANT_PATH = os.path.join(os.path.dirname(__file__), "../../qdrant_storage")

NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


# ══════════════════════════════════════════════════════════════════════════════
#  TẦNG 1: QdrantManager - Vector Database Cục bộ
# ══════════════════════════════════════════════════════════════════════════════
class QdrantManager:
    """
    Quản lý Vector Database Qdrant chạy ở chế độ Embedded (Local).
    - Không cần Docker, không cần server riêng.
    - Ghi thẳng file nhị phân xuống SSD NVMe qua đường dẫn QDRANT_PATH.
    - Sử dụng model MiniLM đa ngôn ngữ để embedding, hỗ trợ truy xuất
      xuyên ngôn ngữ (tiếng Việt hỏi -> tìm được tài liệu tiếng Anh).
    """

    def __init__(self):
        self._client: Optional[QdrantClient] = None
        self._model: Optional[SentenceTransformer] = None

    def _get_client(self) -> QdrantClient:
        """Lazy-init client để tiết kiệm RAM khi không dùng."""
        if self._client is None:
            os.makedirs(QDRANT_PATH, exist_ok=True)
            self._client = QdrantClient(path=QDRANT_PATH)
            logger.info(f"[Qdrant] Đã kết nối Embedded tại: {QDRANT_PATH}")
            self._ensure_collection()
        return self._client

    def _get_model(self) -> SentenceTransformer:
        """Lazy-init model embedding để chỉ tải khi cần thiết."""
        if self._model is None:
            logger.info(f"[Qdrant] Đang tải model embedding: {EMBEDDING_MODEL_NAME}")
            self._model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            logger.info("[Qdrant] Model embedding đã sẵn sàng.")
        return self._model

    def _ensure_collection(self):
        """Tạo collection nếu chưa tồn tại hoặc sai dimension."""
        client = self._client
        existing = [c.name for c in client.get_collections().collections]
        if QDRANT_COLLECTION_NAME not in existing:
            client.create_collection(
                collection_name=QDRANT_COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=QDRANT_VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"[Qdrant] Đã tạo collection: '{QDRANT_COLLECTION_NAME}'")
        else:
            # [FIX] Logic tự động cấu trúc lại CSDL khi đổi embedding model
            try:
                col_info = client.get_collection(collection_name=QDRANT_COLLECTION_NAME)
                current_size = col_info.config.params.vectors.size
                if current_size != QDRANT_VECTOR_SIZE:
                    logger.warning(f"[Qdrant] Collection dimension mismatch (Current: {current_size}, Expected: {QDRANT_VECTOR_SIZE}). Recreating...")
                    
                    # Cảnh báo: qdrant-client (local mode) có một bug rò rỉ bộ nhớ numpy khi delete và recreate collection với size khác nhau trong cùng 1 process.
                    # Khắc phục: Đóng client, xóa trắng thư mục và khởi tạo lại.
                    if self._client:
                        self._client.close()
                        self._client = None
                    import shutil
                    if os.path.exists(QDRANT_PATH):
                        shutil.rmtree(QDRANT_PATH)
                    os.makedirs(QDRANT_PATH, exist_ok=True)
                    self._client = QdrantClient(path=QDRANT_PATH)
                    client = self._client
                    
                    client.create_collection(
                        collection_name=QDRANT_COLLECTION_NAME,
                        vectors_config=VectorParams(
                            size=QDRANT_VECTOR_SIZE,
                            distance=Distance.COSINE,
                        ),
                    )
                    logger.info(f"[Qdrant] Đã recreate collection: '{QDRANT_COLLECTION_NAME}' với size {QDRANT_VECTOR_SIZE}")
                else:
                    logger.info(f"[Qdrant] Collection '{QDRANT_COLLECTION_NAME}' đã tồn tại và đúng dimension ({current_size}).")
            except Exception as e:
                logger.warning(f"[Qdrant] Lỗi kiểm tra collection: {e}. Recreating...")
                try:
                    client.delete_collection(collection_name=QDRANT_COLLECTION_NAME)
                except Exception:
                    pass
                client.create_collection(
                    collection_name=QDRANT_COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=QDRANT_VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"[Qdrant] Đã recreate collection sau lỗi: '{QDRANT_COLLECTION_NAME}'")

    def embed_text(self, text: str) -> List[float]:
        """Chuyển đổi đoạn văn bản thành vector số học."""
        # e5-base yêu cầu prefix 'query: ' cho tìm kiếm
        return self._get_model().encode(f"query: {text}", normalize_embeddings=True).tolist()

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
        model = self._get_model()

        chunk_ids = []
        points = []

        for chunk in chunks:
            chunk_id = str(uuid.uuid4())
            # e5-base yêu cầu prefix 'passage: ' cho tài liệu lưu trữ
            vector = model.encode(f"passage: {chunk['text']}", normalize_embeddings=True).tolist()
            payload = {
                "text": chunk["text"],
                "source": chunk.get("source", "unknown"),
                "page": chunk.get("page", 0),
                **chunk.get("metadata", {}),
            }
            points.append(PointStruct(id=chunk_id, vector=vector, payload=payload))
            chunk_ids.append(chunk_id)

        # Upsert theo batch để tối ưu hiệu suất
        client.upsert(collection_name=QDRANT_COLLECTION_NAME, points=points)
        logger.info(f"[Qdrant] Đã lưu {len(points)} chunks thành công.")
        return chunk_ids

    def search(self, query: str, top_k: int = 5, filter_source: Optional[str] = None) -> List[Dict]:
        """
        Tìm kiếm ngữ nghĩa các chunk liên quan đến câu hỏi.

        Args:
            query: Câu hỏi của người dùng (tiếng Việt hoặc Anh đều được).
            top_k: Số lượng kết quả trả về.
            filter_source: Lọc theo tên file nguồn (optional).

        Returns:
            Danh sách dict chứa chunk_id, score, text và metadata.
        """
        client = self._get_client()
        vector = self.embed_text(query)

        qdrant_filter = None
        if filter_source:
            qdrant_filter = Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=filter_source))]
            )

        # qdrant-client >= 1.7: dùng query_points() thay cho search() đã deprecated
        response = client.query_points(
            collection_name=QDRANT_COLLECTION_NAME,
            query=vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        results = response.points

        return [
            {
                "chunk_id": str(r.id),
                "score": round(r.score, 4),
                "text": r.payload.get("text", ""),
                "source": r.payload.get("source", ""),
                "page": r.payload.get("page", 0),
            }
            for r in results
        ]

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

    def __init__(self):
        self.qdrant = QdrantManager()
        self.neo4j = Neo4jManager()
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
        }
        logger.info(f"[HybridRAG] Nạp xong! Tóm tắt: {summary}")
        return summary

    def retrieve_context(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Luồng truy xuất lai kép theo đặc tả (Bước 5.1 -> 5.2 -> 5.3).

        Chiến lược:
        1. Tìm kiếm vector similarity trực tiếp qua Qdrant (cho câu hỏi chung).
        2. Merge với kết quả từ đồ thị Neo4j (cho câu hỏi có thực thể cụ thể).
        3. Loại bỏ kết quả trùng lặp, sắp xếp theo điểm.

        Args:
            query: Câu hỏi của người dùng.
            top_k: Số lượng đoạn văn trả về.

        Returns:
            Danh sách đoạn văn ngữ cảnh được xếp hạng.
        """
        logger.info(f"[HybridRAG] Truy xuất ngữ cảnh cho query: '{query[:50]}...'")

        # Đường 1: Vector search trực tiếp qua Qdrant
        vector_results = self.qdrant.search(query, top_k=top_k)

        # Đường 2: Graph search qua Neo4j -> lấy chunk_id -> Qdrant
        # [BUG-2 FIX] Bọc neo4j call trong try/except: nếu NEO4J_URI trống hoặc mất mạng
        # → chỉ dùng vector search (graceful degradation), không crash toàn bộ retrieve_context().
        graph_results = []
        try:
            graph_chunk_ids = self.neo4j.query_entity_chunk_ids(keyword=query)
            if graph_chunk_ids:
                graph_results = self.qdrant.get_chunks_by_ids(graph_chunk_ids[:top_k])
                # Gán điểm ưu tiên cho kết quả từ đồ thị (entity-aware retrieval)
                for r in graph_results:
                    r["score"] = r.get("score", 0.85)
                    r["source_method"] = "graph"
        except (ValueError, Exception) as e:
            # ValueError: NEO4J_URI trống. Exception: mất kết nối mạng/timeout.
            logger.warning("[HybridRAG] Neo4j không khả dụng, chỉ dùng vector search: %s", e, exc_info=True)

        for r in vector_results:
            r["source_method"] = "vector"

        # Merge và loại bỏ trùng lặp theo chunk_id
        seen_ids = set()
        merged = []
        for r in graph_results + vector_results:
            cid = r.get("chunk_id", "")
            if cid not in seen_ids:
                seen_ids.add(cid)
                merged.append(r)

        # Sắp xếp theo điểm liên quan giảm dần
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        top_results = merged[:top_k]

        logger.info(f"[HybridRAG] Trả về {len(top_results)} chunks ngữ cảnh.")
        return top_results

    def close(self):
        """Dọn dẹp tài nguyên sau mỗi phiên làm việc."""
        self.qdrant.close()
        self.neo4j.close()
        gc.collect()
        logger.info("[HybridRAG] Đã giải phóng toàn bộ kết nối database.")


# ─── Entry point để test nhanh module này độc lập ─────────────────────────────
if __name__ == "__main__":
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
