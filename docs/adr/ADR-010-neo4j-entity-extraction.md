# ADR-010: Neo4j Entity Extraction - Gemini vs spaCy

## Trạng thái: Accepted

## Bối cảnh
Để phát triển GraphRAG phục vụ truy vấn đề tài NCKH, hệ thống cần trích xuất Thực thể (Entities) và Quan hệ (Relationships) từ tài liệu và nạp vào Neo4j. Chúng ta có hai lựa chọn chính:
1. NLP truyền thống (spaCy, NLTK)
2. LLM-based extraction (Gemini Flash, GPT-4o-mini)

## Quyết định
Chọn **Gemini Flash (GeminiEntityExtractor)** để trích xuất thực thể và quan hệ, bỏ qua spaCy.

## Lý do
1. **Zero-shot NER:** Các thuật ngữ nghiên cứu khoa học tiếng Việt (vd: "Mạng nơ-ron tích chập", "Hệ thống thông tin địa lý") rất khó nhận diện chính xác bằng các mô hình spaCy có sẵn do thiếu tập huấn luyện chuyên sâu. Gemini Flash có khả năng Zero-shot rất tốt với tiếng Việt.
2. **Relationship Extraction:** Trích xuất mối quan hệ phức tạp (A là nguyên nhân của B, C là phương pháp cải tiến từ D) gần như bất khả thi với spaCy nếu không có rules rườm rà. Prompt Engineering trên Gemini dễ dàng xử lý.
3. **Structured Output:** Gemini Flash hỗ trợ JSON mode, giúp việc parse kết quả và đưa vào Neo4j (via `Neo4jManager.upsert_entities()`) ổn định.
4. **Chi phí và tốc độ:** Mẫu Flash rẻ, latency thấp (dưới 1-2s cho chunk nhỏ), hoàn toàn phù hợp để chạy bất đồng bộ trong nền qua `watchdog_listener`.

## Hậu quả
- **Tích cực:** Tăng độ chính xác trích xuất, đặc biệt là với cấu trúc semantic phức tạp. Graph database sẽ giàu thông tin và ý nghĩa hơn.
- **Tiêu cực:** Phụ thuộc vào API bên thứ ba (Google/OpenRouter), chịu giới hạn rate limit và latency mạng. Không chạy hoàn toàn offline được như spaCy.
