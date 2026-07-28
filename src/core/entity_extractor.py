import json
import logging
from typing import List, Dict, Any, Tuple
from src.infrastructure.llm.gemini_client import GeminiLLMClient

logger = logging.getLogger("EntityExtractor")

class GeminiEntityExtractor:
    """
    Trích xuất Entity và Relationship từ văn bản sử dụng Gemini.
    Trả về định dạng phù hợp để lưu vào Neo4j (GraphRAG).
    """
    def __init__(self, llm_client: GeminiLLMClient = None):
        self.llm_client = llm_client or GeminiLLMClient()
        self.prompt_template = """
        Bạn là một chuyên gia phân tích dữ liệu nghiên cứu khoa học.
        Hãy đọc đoạn văn bản sau và trích xuất các thực thể (Entities) và mối quan hệ (Relationships) quan trọng.
        
        Trả về ĐÚNG định dạng JSON sau, không có markdown formatting hay text thừa:
        {
            "entities": [
                {"id": "tên_thực_thể", "label": "LOẠI_THỰC_THỂ"}
            ],
            "relationships": [
                {"source": "tên_thực_thể_1", "target": "tên_thực_thể_2", "type": "LOẠI_QUAN_HỆ"}
            ]
        }
        
        Văn bản:
        {text}
        """

    def extract(self, chunks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        all_entities = []
        all_relationships = []
        
        logger.info(f"[EntityExtractor] Bắt đầu trích xuất entities từ {len(chunks)} chunks...")
        
        for chunk in chunks:
            text = chunk.get("text", "")
            if not text or len(text) < 50:
                continue
                
            prompt = self.prompt_template.replace("{text}", text)
            try:
                # Dùng tính năng stream generator của llm_client và gộp lại
                response_gen = self.llm_client.generate(system_prompt="", user_prompt=prompt, temperature=0.1)
                full_response = "".join(list(response_gen))
                
                # Cố gắng parse JSON
                # Xóa markdown nếu có
                clean_response = full_response.strip()
                if clean_response.startswith("```json"):
                    clean_response = clean_response[7:-3]
                elif clean_response.startswith("```"):
                    clean_response = clean_response[3:-3]
                    
                data = json.loads(clean_response)
                
                if "entities" in data:
                    all_entities.extend(data["entities"])
                if "relationships" in data:
                    all_relationships.extend(data["relationships"])
                    
            except Exception as e:
                logger.error(f"[EntityExtractor] Lỗi trích xuất từ chunk: {e}")
                
        # Loại bỏ trùng lặp
        unique_entities = {e["id"]: e for e in all_entities if "id" in e and "label" in e}.values()
        
        logger.info(f"[EntityExtractor] Trích xuất thành công {len(unique_entities)} entities và {len(all_relationships)} relationships.")
        return list(unique_entities), all_relationships
