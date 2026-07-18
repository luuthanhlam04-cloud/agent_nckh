import os
import json
from qdrant_client import QdrantClient
from src.db.hybrid_rag import QDRANT_PATH, QDRANT_COLLECTION_NAME

def main():
    print(f"--- [Qdrant Data Viewer] ---")
    print(f"Đang kết nối tới DB tại: {QDRANT_PATH}")
    
    if not os.path.exists(QDRANT_PATH):
        print("Không tìm thấy CSDL Qdrant. Vui lòng chạy reindex trước.")
        return

    # Mở kết nối trực tiếp (chỉ đọc)
    client = QdrantClient(path=QDRANT_PATH)
    
    try:
        # Lấy thông tin collection
        collection_info = client.get_collection(QDRANT_COLLECTION_NAME)
        total_points = collection_info.points_count
        print(f"\n✅ Tổng số Chunk hiện có trong DB: {total_points}")
        
        # Duyệt qua các record (Scroll)
        records, next_page_offset = client.scroll(
            collection_name=QDRANT_COLLECTION_NAME,
            limit=1000, # Lấy tối đa 1000 chunks để xem
            with_payload=True,
            with_vectors=False # Không lấy vector để tránh rác màn hình
        )
        
        # Thống kê phân loại
        parent_count = 0
        child_count = 0
        legacy_count = 0
        
        dump_data = []
        
        for r in records:
            c_type = r.payload.get("chunk_type", "legacy")
            if c_type == "parent": parent_count += 1
            elif c_type == "child": child_count += 1
            else: legacy_count += 1
                
            dump_data.append({
                "chunk_id": str(r.id),
                "chunk_type": c_type,
                "parent_id": r.payload.get("parent_id", None),
                "section_title": r.payload.get("section_title", ""),
                "page": r.payload.get("page", 0),
                "text_preview": r.payload.get("text", "").replace("\n", " ")[:150] + "..."
            })
            
        print(f"Thống kê chi tiết:")
        print(f"  - Parent Chunks (Trang gốc): {parent_count}")
        print(f"  - Child Chunks (Đoạn nhỏ để search): {child_count}")
        print(f"  - Legacy Chunks (Chuẩn cũ): {legacy_count}")
        
        # Ghi ra file JSON để sếp dễ soi toàn bộ
        out_file = "qdrant_dump.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(dump_data, f, ensure_ascii=False, indent=4)
            
        print(f"\n📂 Đã xuất danh sách {len(dump_data)} chunks ra file: {out_file}")
        print(f"Sếp hãy mở file {out_file} trong VS Code để xem chi tiết từng chunk nhé!")

    except Exception as e:
        print(f"Lỗi khi đọc Qdrant: {e}")

if __name__ == "__main__":
    main()
