# ADR-001: Gemini Cloud STT thay vì Whisper Local

**Trạng thái:** Accepted  
**Ngày:** 2026-07  
**Sprint:** V4.x → V5.0

---

## Bối cảnh

Hệ thống cần nhận diện giọng nói tiếng Việt (STT). Hai lựa chọn chính:
- **Whisper Local** (`openai/whisper-small`): chạy offline, ~500MB RAM
- **Gemini Cloud API** (`gemini-3.1-flash-lite`): gọi API, cần internet

## Quyết định

Chuyển từ Whisper Local sang **Gemini Cloud API với audio inline**.

## Lý do

1. **Dependency contradiction:** Agent đã phụ thuộc Cloud LLM (OpenRouter) để tư duy. Nếu mất mạng, agent không hoạt động được dù STT có chạy local. Giữ Whisper local ~2GB RAM là lãng phí khi mất mạng = agent cũng hỏng.

2. **Complexity reduction:** Xóa được toàn bộ stack: subprocess server, HTTP IPC, port file reader, ffmpeg dependency, webrtcvad, file WAV tạm trên disk.

3. **Accuracy:** Gemini Flash Lite nhận diện tiếng Việt tốt hơn Whisper Small cho technical vocabulary.

## Hậu quả

### Tích cực
- Xóa 8 layer IPC phức tạp → architecture đơn giản hơn
- Không cần ffmpeg, webrtcvad
- PCM bytes xử lý in-memory, không có temp file

### Tiêu cực / Trade-off
- Phụ thuộc internet (nhưng đã có dependency này từ LLM)
- Tốn API quota Gemini (miễn phí tier đủ dùng hiện tại)
- Latency cao hơn Whisper local (bù lại bằng PTT mode để user kiểm soát)
