import os
import shutil
import glob
from dotenv import load_dotenv

from src.db.hybrid_rag import QDRANT_PATH, QDRANT_COLLECTION_NAME, QdrantManager
from src.utils.parser import PDFParser

def main():
    load_dotenv()
    print("--- [Reindex Tool] ---")
    
    # 1. Xóa DB cũ
    if os.path.exists(QDRANT_PATH):
        print(f"[1] Xóa CSDL Qdrant cũ tại {QDRANT_PATH}...")
        shutil.rmtree(QDRANT_PATH)
    else:
        print("[1] Không tìm thấy DB Qdrant cũ.")

    # 2. Khởi tạo DB mới (sẽ tự động tạo lại collection)
    print("[2] Khởi tạo Qdrant mới...")
    qdrant = QdrantManager()
    
    # 3. Quét các file PDF trong 02_Knowledge
    pdf_files = glob.glob(r"Obsidian_Vault\02_Knowledge\*.pdf")
    if not pdf_files:
        print("[!] Không tìm thấy file PDF nào trong Obsidian_Vault\\02_Knowledge.")
        print("[!] Bạn có thể dùng giao diện (kéo thả vào Inbox) để thêm tài liệu.")
        return

    print(f"[3] Bắt đầu ingest {len(pdf_files)} files...")
    parser = PDFParser()
    
    total_chunks = 0
    for file_path in pdf_files:
        print(f"  -> Đang xử lý: {file_path}")
        chunks = parser.parse(file_path)
        print(f"     => Đã tạo {len(chunks)} chunks (Parent & Child). Đang upsert...")
        qdrant.upsert_chunks(chunks)
        total_chunks += len(chunks)

    print(f"\n[HOÀN TẤT] Đã reindex {total_chunks} chunks thành công!")

if __name__ == "__main__":
    main()
