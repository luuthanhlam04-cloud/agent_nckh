import os
import sys
import logging
import json
import statistics

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.hybrid_rag import QdrantManager, Neo4jManager, QDRANT_COLLECTION_NAME
from qdrant_client import models

logging.basicConfig(level=logging.WARNING, format="%(message)s") # Giảm bớt log info mặc định để Dashboard sạch sẽ
logger = logging.getLogger("KnowledgeHealth")

def run_health_check():
    print("=" * 60)
    print("                KNOWLEDGE HEALTH DASHBOARD                ")
    print("=" * 60)
    
    qdrant_mgr = QdrantManager()
    neo4j_mgr = Neo4jManager()
    
    # ---- DATA GATHERING ----
    qdrant_client = qdrant_mgr._get_client()
    qdrant_chunks = {}
    
    try:
        records, _ = qdrant_client.scroll(
            collection_name=QDRANT_COLLECTION_NAME,
            limit=10000,
            with_payload=True
        )
        for r in records:
            qdrant_chunks[r.id] = r.payload
    except Exception as e:
        logger.error(f"Lỗi đọc Qdrant: {e}")
        
    documents = set()
    chunk_lengths = []
    
    for cid, payload in qdrant_chunks.items():
        source = payload.get("source", "unknown")
        documents.add(source)
        chunk_lengths.append(len(payload.get("text", "")))
        
    avg_chunk_len = statistics.mean(chunk_lengths) if chunk_lengths else 0
        
    neo4j_nodes = []
    neo4j_edges_count = 0
    neo4j_configured = False
    
    try:
        neo4j_driver = neo4j_mgr._get_driver()
        neo4j_configured = True
    except Exception as e:
        pass
        
    if neo4j_configured:
        try:
            with neo4j_driver.session() as session:
                result = session.run("MATCH (n) RETURN n.name as name, labels(n)[0] as type, n.qdrant_chunk_ids as chunk_ids")
                for record in result:
                    chunk_ids = record["chunk_ids"]
                    if isinstance(chunk_ids, str):
                        try:
                            chunk_ids = json.loads(chunk_ids)
                        except:
                            pass
                    neo4j_nodes.append({
                        "name": record["name"],
                        "type": record["type"],
                        "chunk_ids": chunk_ids if chunk_ids else []
                    })
                
                # Edges count
                edges_res = session.run("MATCH ()-[r]->() RETURN count(r) as count")
                neo4j_edges_count = edges_res.single()["count"]
        except Exception as e:
            neo4j_configured = False
            
    # ---- INTEGRITY CHECKS ----
    orphan_chunks = 0
    broken_references = 0
    duplicate_chunks = 0
    duplicate_nodes = 0
    
    # Check 1: Duplicate Chunks
    text_hashes = {}
    for cid, payload in qdrant_chunks.items():
        text = payload.get("text", "")
        import hashlib
        h = hashlib.md5(text.encode('utf-8')).hexdigest()
        if h in text_hashes:
            duplicate_chunks += 1
        else:
            text_hashes[h] = cid
            
    # Check 2: Graph Checks
    if neo4j_configured:
        referenced_chunk_ids = set()
        node_names = {}
        for node in neo4j_nodes:
            if isinstance(node["chunk_ids"], list):
                referenced_chunk_ids.update(node["chunk_ids"])
            
            # Check duplicate nodes (same name, different types)
            name = node["name"].lower()
            if name in node_names and node_names[name] != node["type"]:
                duplicate_nodes += 1
            else:
                node_names[name] = node["type"]
                
        orphan_chunks = len(set(qdrant_chunks.keys()) - referenced_chunk_ids)
        broken_references = len(referenced_chunk_ids - set(qdrant_chunks.keys()))
        
    # ---- REPORTING ----
    print("\n[1] HEALTH REPORT (RAW METRICS)")
    print("-" * 60)
    print(f" Documents       : {len(documents)}")
    print(f" Chunks          : {total_chunks}")
    print(f" Avg Chunk Length: {avg_chunk_len:.0f} chars")
    print("-" * 60)
    print(f" Qdrant Status   : {'✓ OK' if total_chunks > 0 else '⚠ Empty'}")
    print(f" Neo4j Status    : {'✓ OK' if neo4j_configured else '⚠ Not configured'}")
    if neo4j_configured:
        print(f" Graph Nodes     : {len(neo4j_nodes)}")
        print(f" Graph Edges     : {neo4j_edges_count}")
    print("-" * 60)
    print(f" Duplicate Chunks: {duplicate_chunks}")
    if neo4j_configured:
        print(f" Orphan Chunks   : {orphan_chunks}")
        print(f" Broken Refs     : {broken_references}")
        print(f" Duplicate Nodes : {duplicate_nodes}")
        
    print("\n[2] SUGGESTED ACTIONS")
    print("-" * 60)
    actions = []
    if duplicate_chunks > 0:
        actions.append("- Merge/Delete duplicate chunks in Qdrant.")
    if orphan_chunks > 0:
        actions.append("- Remove orphan chunks or extract entities to link them in Neo4j.")
    if broken_references > 0:
        actions.append("- Remove broken references from Neo4j (chunk_ids no longer in Qdrant).")
    if duplicate_nodes > 0:
        actions.append("- Merge duplicate entities in Neo4j (same name, different types).")
    if not neo4j_configured:
        actions.append("- Configure NEO4J_URI in .env to enable Graph Health checks.")
    if len(documents) == 0:
        actions.append("- Ingest more documents to build the knowledge base.")
        
    if not actions:
        print("- No actions required. Keep up the good work!")
    else:
        for action in actions:
            print(action)
            
    print("\n" + "=" * 60)
    qdrant_mgr.close()
    neo4j_mgr.close()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    run_health_check()
