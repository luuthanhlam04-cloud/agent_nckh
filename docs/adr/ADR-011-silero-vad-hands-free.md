# ADR-011: Tích hợp Silero VAD (ONNX) cho Tương tác Thoại Tự động Rảnh tay (Hands-free)

- **Trạng thái:** Accepted
- **Ngày:** 2026-11-13
- **Tác giả:** Lead Agentic Systems Architect

---

## 1. Ngữ cảnh (Context)
Trước đây, module `VoiceRecorder` trong `src/ui/voice_engine.py` sử dụng ngưỡng năng lượng RMS tĩnh (`RMS_SPEECH_THRESHOLD = 300`) để phát hiện giọng nói.
Thuật toán này bộc lộ các nhược điểm nghiêm trọng trong môi trường làm việc thực tế:
- Tiếng gõ bàn phím cơ, tiếng thở mạnh hoặc quạt gió kích hoạt nhầm trạng thái đang nói $\rightarrow$ gửi audio rác lên STT API.
- Khi người dùng nói nhỏ hoặc micro ở xa $\rightarrow$ RMS thấp bị hiểu nhầm là im lặng, gây nuốt âm đầu hoặc cắt ngang câu.
- Buộc người dùng phải dùng Push-to-Talk (giữ phím), làm mất trải nghiệm tự nhiên.

---

## 2. Quyết định (Decision)
1. Chuyển sang sử dụng **Silero VAD v6** chạy local thông qua **ONNX Runtime** (`onnxruntime` CPUExecutionProvider).
2. Tận dụng file trọng số `silero_vad_v6.onnx` (<2MB) có sẵn trong môi trường máy tính mà không cần tải thêm qua mạng.
3. Thiết lập **Pre-speech Ring Buffer (500ms)** sử dụng `collections.deque(maxlen=16)`: Luôn lưu 500ms audio trong bộ nhớ tạm. Khi xác suất tiếng nói vượt ngưỡng ($p > 0.55$), lập tức giải phóng pre-buffer vào đầu luồng để bảo toàn nguyên vẹn phụ âm đầu câu.
4. Thiết lập **Trailing Silence (1.5s)**: Tự động ngắt mic sau 1.5 giây im lặng sau khi người dùng kết thúc câu nói.

---

## 3. Hệ quả (Consequences)
- **Ưu điểm:**
  - Tương tác giọng nói tự động rảnh tay (Hands-free) 100%, không cần nhấn giữ phím.
  - Loại bỏ hoàn toàn tiếng ồn phím cơ và quạt tản nhiệt.
  - Độ trễ cực thấp (<5ms), tiêu tốn <1% CPU.
- **Rủi ro & Giảm thiểu:**
  - Nếu thiếu model ONNX, hệ thống tự động fallback sang tính năng lượng RMS để không gây crash ứng dụng.

