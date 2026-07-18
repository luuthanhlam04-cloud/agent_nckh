import os
from dotenv import load_dotenv
from src.db.hybrid_rag import QdrantManager

def main():
    load_dotenv()
    print("--- [Test Search Sprint B & C] ---")
    
    qdrant = QdrantManager()
    
    query = "các tính chất để đánh giá câu trả lời của ragas là gì"
    print(f"Câu hỏi: '{query}'\n")
    
    results = qdrant.search(query, top_k=6)
    
    for i, res in enumerate(results):
        print(f"--- Top {i+1} (Score: {res['score']}) ---")
        print(f"Chunk ID: {res['chunk_id']}")
        print(f"Source: {res['source']} | Page: {res['page']}")
        
        highlight = res.get('highlight', '')
        if highlight:
            print(f"🎯 Child Context (Matched): {highlight[:100]}...")
            
        text = res.get('text', '')
        print(f"📄 Parent Text (LLM Context): {text[:200]}...")
        print("-" * 50 + "\n")

if __name__ == "__main__":
    main()
