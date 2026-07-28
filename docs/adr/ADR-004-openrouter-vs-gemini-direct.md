# ADR-004: OpenRouter cho Answer Generation thay vì Gemini trực tiếp

**Trạng thái:** Accepted  
**Ngày:** 2026-07  
**Sprint:** V3.x

---

## Bối cảnh

Cần LLM chất lượng cao để generate câu trả lời RAG. Lựa chọn:
- **Gemini API trực tiếp** (Google AI Studio): 1 provider
- **OpenRouter**: aggregator, truy cập nhiều model qua 1 API key

## Quyết định

Dùng **OpenRouter** cho WorkerEngine (answer generation), giữ **Gemini API trực tiếp** cho SelfCritiqueAgent và GeminiSTT.

## Lý do

1. **Model flexibility:** OpenRouter cho phép thay đổi model (Gemini Pro → Claude → GPT-4) bằng cách đổi 1 string constant, không cần thay đổi code.

2. **Cost optimization:** OpenRouter hỗ trợ routing tự động sang model rẻ hơn khi quota hết.

3. **Separation of concerns:** Answer generation (chất lượng cao, tốn cost) tách khỏi Critique (nhanh, miễn phí tier).

## Hậu quả

### Tích cực
- Swap model không cần sửa code
- Dự phòng khi 1 provider có downtime

### Tiêu cực / Trade-off
- 2 API key cần manage (GEMINI_API_KEY + OPENROUTER_API_KEY)
- OpenRouter thêm 1 hop network (latency +50-100ms)
- OpenRouter có thể rate-limit riêng

## Ghi chú cho Sprint 4

Khi tạo `ILLMClient` interface và tách `OpenRouterLLMClient` / `GeminiLLMClient`, cần giữ đúng phân chia này:
- `WorkerEngine` → `OpenRouterLLMClient`
- `SelfCritiqueAgent` → `GeminiLLMClient`
