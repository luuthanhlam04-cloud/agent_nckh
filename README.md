# Digital Scholar — AI Research Assistant (Agent V5.0)

> **Trợ lý nghiên cứu học thuật chạy nền (Background Daemon)** kết hợp Hybrid RAG (Vector + Graph), nhận diện giọng nói qua Gemini Cloud API, giao diện Spotlight kiểu macOS, và tự động hóa tác vụ hệ điều hành.

---

## 🧭 Mục lục

1. [Tổng quan dự án](#1-tổng-quan-dự-án)
2. [Kiến trúc tổng thể](#2-kiến-trúc-tổng-thể)
3. [Luồng xử lý chi tiết](#3-luồng-xử-lý-chi-tiết)
4. [Các module và trách nhiệm](#4-các-module-và-trách-nhiệm)
5. [Mô hình AI và dữ liệu](#5-mô-hình-ai-và-dữ-liệu)
6. [Hệ thống Voice (Giọng nói)](#6-hệ-thống-voice-giọng-nói)
7. [Cài đặt và chạy](#7-cài-đặt-và-chạy)
8. [Cấu trúc thư mục](#8-cấu-trúc-thư-mục)
9. [Quy tắc kiến trúc cứng](#9-quy-tắc-kiến-trúc-cứng)
10. [Trạng thái hiện tại và hạn chế đã biết](#10-trạng-thái-hiện-tại-và-hạn-chế-đã-biết)

---

## 1. Tổng quan dự án

### Dự án này là gì?

**Digital Scholar** là một **AI Agent chạy nền trên Windows**, hoạt động 24/7 như một daemon — không có cửa sổ thường trực. Người dùng triệu hồi bằng phím tắt `Ctrl+Space` → xuất hiện cửa sổ Spotlight kiểu macOS → nhập câu hỏi hoặc lệnh → cửa sổ tự ẩn sau khi xử lý xong.

### Giải quyết vấn đề gì?

Sinh viên/nhà nghiên cứu thường có hàng chục paper PDF/PPTX trên máy tính. Vấn đề:
- Không thể tìm kiếm **ngữ nghĩa** qua đống tài liệu đó
- Phải mở từng file để tìm thông tin
- Chatbot online không biết nội dung tài liệu cá nhân

Digital Scholar giải quyết bằng cách:
1. **Tự động hút** tất cả PDF/PPTX thả vào `01_Inbox/` → phân tích → lưu vào vector database cục bộ
2. **Trả lời câu hỏi** dựa trên nội dung tài liệu thật sự (RAG) kết hợp web search khi cần
3. **Điều khiển máy tính** bằng giọng nói hoặc text (mở app, YouTube, website...)

### Tech Stack tóm tắt

| Tầng | Công nghệ |
|------|-----------|
| UI | PyQt6 (Spotlight popup, frameless, always-on-top) |
| STT (giọng → text) | Gemini Cloud API (`gemini-3.1-flash-lite`, inline audio) |
| TTS (text → giọng) | Edge-TTS (Azure Neural Voice, streaming) |
| LLM chính (trả lời) | Gemini 2.5 Pro qua OpenRouter (streaming) |
| LLM phụ (chấm điểm) | Gemini 3.1 Flash Lite (Gemini API trực tiếp) |
| Vector DB | Qdrant (embedded local, không cần Docker) |
| Graph DB | Neo4j Aura Free Tier (cloud) |
| Embedding Model | `intfloat/multilingual-e5-base` (768 dims, hỗ trợ tiếng Việt) |
| Document Parser | PyMuPDF (PDF) + python-pptx (PPTX) |
| Intent Classification | Sentence Transformer + Cosine Similarity (semantic matching) |

---

## 2. Kiến trúc tổng thể

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NGƯỜI DÙNG                                                             │
│    ↓ Ctrl+Space (hotkey toàn cục)                                       │
│    ↓ Gõ text hoặc giữ Alt+Space (Push-to-Talk)                         │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  SpotlightWindow (PyQt6 - Main Thread - KHÔNG bao giờ block)    │   │
│  │    ↓ signal pyqtSignal (thread-safe)                            │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌────────────────────────┐  │   │
│  │  │  AIWorker   │  │  TTSWorker  │  │  VoiceWorker           │  │   │
│  │  │  (QThread)  │  │  (QThread)  │  │  (QThread)             │  │   │
│  │  │  Gọi AI     │  │  Azure TTS  │  │  Gemini STT            │  │   │
│  │  └──────┬──────┘  └─────────────┘  └────────────────────────┘  │   │
│  └─────────┼────────────────────────────────────────────────────────┘   │
│            ↓                                                             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  SemanticInterceptor (Trước khi vào AI - Xử lý Local)          │    │
│  │    → Embedding câu hỏi → So sánh cosine với ~50 anchor phrases │    │
│  │    → Nếu match cao: xử lý LOCAL (thời gian, lệnh OS, copy...)  │    │
│  │    → Nếu không match: chuyển xuống Orchestrator                │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│            ↓                                                             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  ReActOrchestrator (State Machine - 2 luồng)                    │    │
│  │                                                                  │    │
│  │  Fast-Track (daily_task):                                        │    │
│  │    RAG (top_k=3) + Web search → LLM generate (nhanh)           │    │
│  │                                                                  │    │
│  │  Deep-Track (research_query):                                    │    │
│  │    RAG (top_k=5)                                                │    │
│  │      → SelfCritiqueAgent chấm điểm context (0-10)              │    │
│  │      → Điểm ≥ 8: Generate luôn                                  │    │
│  │      → Điểm < 8: Web search → Critique lại (tối đa 3 vòng)     │    │
│  │      → WorkerEngine generate streaming answer                    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│            ↓                                                             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  HybridRAG (Dual Database Layer)                                │    │
│  │    ┌──────────────────┐    ┌──────────────────────────────┐    │    │
│  │    │  Qdrant (Local)  │    │  Neo4j Aura (Cloud)           │    │    │
│  │    │  Vector search   │    │  Graph entity search          │    │    │
│  │    │  768-dim cosine  │    │  → chunk_ids → Qdrant fetch  │    │    │
│  │    └──────────────────┘    └──────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Luồng xử lý chi tiết

### 3.1. Luồng từ khi người dùng nhập text đến khi có câu trả lời

```
[1] User gõ text + Enter
        ↓
[2] SpotlightWindow._on_submit()
     → Gọi SemanticInterceptor.intercept(text)
        ↓
[3] SemanticInterceptor phân loại intent:
     a. Embed text bằng multilingual-e5-base (tái dùng model đang có trong RAM)
     b. Cosine similarity với ~50 anchor phrases trong intents.json
     c. Nếu score ≥ 0.87 → thực thi intent local:
        - GREETING     → trả chuỗi chào hỏi, mode "fast"
        - TIME_QUERY   → trả giờ/ngày hiện tại, mode "fast"
        - OS_YOUTUBE   → yt-dlp tìm video → webbrowser.open(), mode "ninja"
        - OS_APP       → subprocess.Popen("start <app>"), mode "ninja"
        - OS_WEBSITE   → DuckDuckGo "I'm Feeling Lucky", mode "ninja"
        - OBSIDIAN_SAVE→ ghi vào 03_Agent_Memory/Profile.md, mode "ninja"
        - EXPORT_DOCX  → DocxExporter pipeline, mode "router"
        - FORCE_WEB    → bỏ qua RAG, tìm web luôn, mode "router"
        - SMALL_TALK   → chuyển xuống LLM fast-track, mode "router"
     d. Nếu score < 0.87 → research_query → chuyển xuống Orchestrator
        ↓
[4] AIWorker (QThread) nhận:
     - dict {"intent": "research_query", "query": text}  hoặc
     - dict {"intent": "daily_task", "query": text}       hoặc
     - dict {"intent": "EXPORT_DOCX", "topic": text}
        ↓
[5] process_user_input() điều phối (Coordinator trong main.py):
     - intent == "EXPORT_DOCX"    → DocxExporter.export(topic)
     - intent == "daily_task"     → orchestrator.run(intent="daily_task")
     - intent == "research_query" → orchestrator.run(intent="research_query")
        ↓
[6] ReActOrchestrator.run():

     FAST-TRACK (daily_task):
       ├─ RAG: HybridRAG.retrieve_context(top_k=3)
       ├─ Web: DDGS.text(query, max_results=3) (song song với RAG)
       └─ Generate: WorkerEngine → streaming chunks → sig_chunk → UI

     DEEP-TRACK (research_query):
       ├─ Node RETRIEVE: HybridRAG.retrieve_context(top_k=5)
       ├─ Node CRITIQUE: SelfCritiqueAgent.evaluate()
       │    → Gemini Flash Lite chấm điểm JSON:
       │      {"relevance_score": 0-10, "answerability_score": 0-10,
       │       "action_required": "proceed"|"force_web_search"}
       │    → avg_score ≥ 8.0: proceed
       │    → avg_score < 8.0: web search (vòng lặp tối đa 3 lần)
       ├─ Node WEB_SEARCH (nếu cần): DDGS → thêm vào context_chunks
       └─ Node GENERATE: WorkerEngine.generate() → streaming
        ↓
[7] Mỗi chunk text → sig_chunk → SpotlightWindow._on_ai_chunk() → hiện lên UI
    Mỗi câu hoàn chỉnh → sig_sentence → TTSWorker → Azure Edge-TTS → QMediaPlayer
        ↓
[8] Hoàn thành → memory.add(user_input, full_answer)
```

### 3.2. Luồng nạp tài liệu (Inbox Watcher)

```
[1] User thả file PDF/PPTX vào thư mục: Obsidian_Vault/01_Inbox/
        ↓
[2] Watchdog Observer phát hiện file mới
     → Debounce 2s (chờ file ghi xong hoàn toàn)
     → Poll size file mỗi 0.5s, stable trong 6s mới xử lý
        ↓
[3] asyncio Worker Thread (InboxWatcher) xử lý:
     a. PDFParser: PyMuPDF đọc từng trang
        → _extract_blocks_with_headings(): phát hiện heading bằng font size median
        → chunk_by_paragraph(): chia chunk MAX 600 chars, overlap 150 chars
        → Mỗi chunk có: {text, source, page, metadata.section_title}
     
     b. PPTXParser: python-pptx trích text từ shapes
        → Gemini Flash Lite làm sạch và cấu trúc hóa nội dung mỗi slide
        → Sleep 4s giữa mỗi slide (rate limit Gemini 15 req/phút)
        ↓
[4] Parent-Child Chunking:
     - Parent chunk: đoạn văn gốc lớn (~600 chars)
     - Child chunk: đoạn con nhỏ hơn (embedded để search chính xác)
     - Child lưu trường "parent_id" trỏ về Parent
        ↓
[5] Qdrant.upsert_chunks():
     - Encode "passage: {text}" bằng multilingual-e5-base → vector 768 dims
     - Lưu vào collection "scholar_knowledge"
     - Trả về list chunk_id (UUID)
        ↓
[6] ⚠️ Neo4j entity extraction: CHƯA IMPLEMENT
     (Tech debt: hiện tại bỏ qua bước này, Neo4j graph rỗng)
        ↓
[7] Lưu Markdown bản bóc tách → Obsidian_Vault/02_Knowledge/{stem}.md
[8] Di chuyển file gốc → 02_Knowledge/ (đánh dấu đã xử lý)
```

### 3.3. Luồng Voice (Push-to-Talk)

```
[1] User giữ Alt+Space
     → GlobalHotkeyWorker phát sig_ptt_start
     → VoiceRecorder.start_recording() (pyaudio, 16kHz mono, int16)
        ↓
[2] User nhả Alt+Space
     → GlobalHotkeyWorker phát sig_ptt_stop
     → VoiceRecorder.stop_recording() → trả về raw PCM bytes
        ↓
[3] VoiceWorker (QThread):
     → GeminiSTT.transcribe(pcm_bytes):
        - Wrap PCM bytes → WAV header trong memory (không lưu file)
        - Gọi Gemini API: gemini-3.1-flash-lite, audio inline
        - Trả về text transcript
        ↓
[4] Kết quả text → _on_voice_finished() → điền vào input_box → _on_submit()
     → Tiếp tục luồng xử lý text bình thường (mục 3.1)
```

### 3.4. Memory Consolidation (Chạy hàng đêm lúc 0:00)

```
APScheduler BackgroundScheduler trigger lúc 0:00:
  → Doc ConversationMemory._window (5 cặp Q&A gần nhất trong RAM)
  → Gọi Gemini Flash: Map-Reduce lọc nội dung học thuật quan trọng
  → Ghi/ghi đè Obsidian_Vault/03_Agent_Memory/Profile.md
  
Catch-up logic: nếu máy ngủ và bỏ lỡ cronjob → chạy bù khi khởi động lại
(kiểm tra file .consolidation_state so sánh ngày cuối đã consolidate)
```

---

## 4. Các module và trách nhiệm

### Sơ đồ dependency

```
main.py
├── src/ui/spotlight.py          ← UI, Workers, hotkey
├── src/core/orchestrator.py     ← ReAct state machine, WorkerEngine, SelfCriti que
├── src/core/semantic_interceptor.py ← Intent classification (cosine similarity)
├── src/core/conversation_memory.py  ← Short-term memory (deque, window=5)
├── src/db/hybrid_rag.py         ← QdrantManager + Neo4jManager + HybridRAG
├── src/utils/parser.py          ← PDFParser, PPTXParser, chunk_by_paragraph
├── src/utils/watchdog_listener.py   ← InboxWatcher, InboxEventHandler
├── src/services/memory_consolidator.py ← APScheduler + Gemini Map-Reduce
├── src/services/docx_exporter.py       ← Xuất báo cáo Word
└── src/ui/voice_engine.py       ← GeminiSTT, VoiceRecorder
```

### Chi tiết từng module

#### `main.py` (419 dòng)
- Entry point duy nhất
- Boot sequence: Database → Watcher → Core AI → Consolidator → UI
- Hàm `process_user_input()` là **Coordinator** trung tâm nhận intent từ Interceptor và điều phối xuống Orchestrator hoặc DocxExporter
- Đăng ký SIGTERM/SIGINT handler để shutdown sạch

#### `src/ui/spotlight.py` (1325 dòng — God File)
Chứa 6 class:
- **`AIWorker`**: Chạy `process_user_input()` trong QThread, emit `sig_chunk` từng delta text để typewriter effect
- **`TTSWorker`**: Queue-based, nhận từng câu hoàn chỉnh từ `sig_sentence`, gọi Azure Edge-TTS, download MP3 chunk, emit path cho `QMediaPlayer`
- **`VoiceWorker`**: Nhận raw PCM bytes, gọi `GeminiSTT.transcribe()`, emit text
- **`GlobalHotkeyWorker`**: `keyboard.wait()` blocking trong thread riêng, phát signal khi `Ctrl+Space` (toggle UI) và `Alt+Space` PTT events
- **`SpotlightWindow`**: Main window, 3 mode (FAST/NINJA/AI), drag-to-move, animation expand/collapse, TTS playlist manager
- **`setup_system_tray()`**: System Tray icon + right-click menu

#### `src/core/orchestrator.py` (727 dòng)
Chứa 3 class + constants:
- **`WorkerEngine`**: Lazy-init OpenAI client trỏ về OpenRouter. Gọi `gemini-2.5-pro` (hoặc model được cấu hình). Streaming response.
- **`SelfCritiqueAgent`**: Gọi `gemini-3.1-flash-lite` với JSON mode để chấm điểm context (0-10), trả về `SelfCritiqueResult` Pydantic model
- **`ReActOrchestrator`**: State machine với 4 nodes (`_node_retrieve`, `_node_critique`, `_node_web_search`, `_node_generate`). Sử dụng `AgentState` TypedDict tương thích LangGraph

#### `src/core/semantic_interceptor.py` (276 dòng)
- Nhận embed function từ `QdrantManager.embed_text` (tái dùng model đã có trong RAM, không nạp model mới)
- Load `intents.json` (16 intents với ~50 anchor phrases)
- Khởi động background thread để encode tất cả anchors thành vectors (không block boot)
- `intercept()`: encode input → cosine với tất cả anchors → execute intent nếu match

#### `src/db/hybrid_rag.py` (673 dòng)
- **`QdrantManager`**: Lazy-init embedded Qdrant, tự tạo/migrate collection khi đổi model
- **`Neo4jManager`**: Lazy-init Neo4j driver, MERGE node/relationship
- **`HybridRAG.retrieve_context()`**: Song song Qdrant vector search + Neo4j graph search → merge → dedup → sort by score

#### `src/utils/parser.py` (536 dòng)
- **`chunk_by_paragraph()`**: Recursive chunking, nhận diện heading Markdown và font size để xác định Section boundary
- **`PDFParser`**: Heading-aware parsing, lọc dòng rác (số trang, tiêu đề lặp)
- **`PPTXParser`**: Text extraction + Gemini cleanup mỗi slide
- **`parse_document()`**: Entry point, tự detect PDF/PPTX theo extension

#### `src/utils/watchdog_listener.py` (398 dòng)
- Watchdog Observer + asyncio event loop trong cùng Worker Thread
- Debounce 2s + poll size stability trước khi xử lý file
- `run_in_executor()` để chạy sync parser trong async context

#### `src/services/memory_consolidator.py` (308 dòng)
- APScheduler `BackgroundScheduler` (thread-based, không xung đột Qt event loop)
- Persistence: `.consolidation_state` JSON file lưu ngày cuối đã consolidate
- Gemini Flash Map-Reduce: lọc nội dung học thuật từ conversation history

#### `src/services/docx_exporter.py` (344 dòng)
- Nhận topic từ intent `EXPORT_DOCX`
- Gọi Orchestrator RAG với `top_k=10`
- Build Word document: Times New Roman 12, line spacing 1.5, có Tài liệu tham khảo section
- Lưu vào Desktop `{topic}_{datetime}.docx`

#### `src/ui/voice_engine.py` (340 dòng)
- **`VoiceRecorder`**: pyaudio stream, RMS-based VAD, trả raw PCM bytes
- **`GeminiSTT`**: Thread-safe Singleton, wrap PCM → WAV header in-memory → Gemini API

---

## 5. Mô hình AI và dữ liệu

### 5.1. Embedding Model: `intfloat/multilingual-e5-base`

- **Kích thước vector:** 768 dimensions
- **Đặc điểm:** Hỗ trợ tìm kiếm xuyên ngôn ngữ (tiếng Việt hỏi → tìm được tài liệu tiếng Anh)
- **Prefix bắt buộc:** `"passage: {text}"` khi lưu (ingest), `"query: {text}"` khi tìm (search)
- **Tải khi:** Lần đầu tiên cần embed — lazy init

### 5.2. Chunking Strategy: Parent-Child

```
Tài liệu gốc (PDF/PPTX)
    ↓ PDFParser/PPTXParser
Parent Chunks (~600 chars, 1-2 đoạn văn, ngữ cảnh đầy đủ)
    ├── Child Chunk A (~150-200 chars, có parent_id)  ← Vector search target
    ├── Child Chunk B (~150-200 chars, có parent_id)  ← Vector search target
    └── Child Chunk C (~150-200 chars, có parent_id)  ← Vector search target

Khi search: tìm Child → lấy parent_id → fetch Parent về cho LLM
(Child nhỏ = vector đặc trưng hơn, Parent lớn = context đủ cho LLM)
```

### 5.3. Qdrant Collection Schema

Collection name: `scholar_knowledge`

```json
{
  "id": "uuid-v4",
  "vector": [768 floats],
  "payload": {
    "chunk_type": "parent" | "child" | "legacy",
    "text": "nội dung văn bản",
    "source": "ten_file.pdf",
    "page": 3,
    "parent_id": "uuid-của-parent (chỉ có ở child)",
    "section_title": "Introduction"
  }
}
```

### 5.4. Obsidian Vault Structure

```
Obsidian_Vault/
├── 01_Inbox/       ← Thả PDF/PPTX vào đây để ingest tự động
├── 02_Knowledge/   ← File đã xử lý + bản Markdown bóc tách
└── 03_Agent_Memory/
    └── Profile.md  ← Memory consolidation viết vào đây hàng đêm
```

### 5.5. LLM Configuration

| Model | Dùng cho | API | Giá |
|-------|----------|-----|-----|
| `gemini-3.1-flash-lite` | SelfCritiqueAgent chấm điểm context | Gemini API trực tiếp | Miễn phí |
| `gemini-3.1-flash-lite` | GeminiSTT transcribe | Gemini API trực tiếp | Miễn phí |
| `google/gemini-2.5-pro` | WorkerEngine generate answer | OpenRouter | Tính phí |

---

## 6. Hệ thống Voice (Giọng nói)

### Kiến trúc sau khi refactor (đã xóa Whisper)

| Cũ (V4) | Mới (V5) |
|---------|---------|
| Whisper Local (~2GB RAM) | Gemini STT Cloud API |
| subprocess server, HTTP IPC | Inline audio, direct API call |
| ffmpeg dependency | Không cần ffmpeg |
| File WAV tạm trên disk | PCM bytes in-memory |
| webrtcvad | RMS threshold đơn giản |

### Hai chế độ Voice

1. **VAD Mode** (Voice Activity Detection): `Ctrl+Shift+Space` bật/tắt. Mic tự động ngừng sau 1.5s im lặng.
2. **PTT Mode** (Push-to-Talk — mặc định): Giữ `Alt+Space` để nói, nhả để gửi. Nhanh hơn, không có nguy cơ ghi nhầm.

Chế độ được cấu hình bằng `VOICE_MODE=ptt` trong `.env`.

### Các phím tắt

| Phím | Tác dụng |
|------|---------|
| `Ctrl+Space` | Hiện/ẩn Spotlight |
| `Alt+Space` (giữ) | PTT — ghi âm (PTT mode) |
| `Ctrl+Shift+Space` | Toggle VAD mic |
| `Escape` | Ẩn cửa sổ |

---

## 7. Cài đặt và chạy

### Yêu cầu hệ thống

- **OS:** Windows 10/11 (64-bit)
- **Python:** 3.11.x
- **RAM:** Tối thiểu 8GB (multilingual-e5-base ~500MB, Qdrant ~100MB)
- **Quyền:** Administrator (để keyboard hook toàn cục)
- **Internet:** Cần kết nối (Gemini API, OpenRouter, Neo4j Aura, Edge-TTS, DuckDuckGo)

### Bước 1: Clone và cài thư viện

```bash
git clone <repo_url>
cd agent_nckh
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Bước 2: Tạo file `.env`

```env
# === AI APIs ===
GEMINI_API_KEY=AIza...          # Google AI Studio → https://aistudio.google.com
OPENROUTER_API_KEY=sk-or-...    # OpenRouter → https://openrouter.ai

# === Graph Database (có thể để trống nếu không dùng GraphRAG) ===
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password

# === Obsidian Vault ===
OBSIDIAN_VAULT_PATH=C:/Users/YourName/Documents/Obsidian_Vault

# === Voice Mode ===
VOICE_MODE=ptt      # hoặc "vad"
```

### Bước 3: Chạy

```bash
# Chạy bình thường (cần chạy với quyền Administrator cho hotkey)
python main.py

# Hoặc dùng Run As Administrator trong Windows
```

### Bước 4: Nạp tài liệu

Thả bất kỳ file `.pdf` hoặc `.pptx` vào thư mục `Obsidian_Vault/01_Inbox/`. Hệ thống sẽ tự động phát hiện và xử lý (log xuất hiện trong terminal và file `agent.log`).

---

## 8. Cấu trúc thư mục

```
agent_nckh/
├── main.py                         ← Entry point duy nhất
├── requirements.txt
├── .env                            ← API keys (KHÔNG commit git)
├── ARCHITECTURE_RULES.md           ← "Hiến pháp kỹ thuật" — quy tắc bắt buộc
├── agent.log                       ← Log runtime (tự tạo)
├── .consolidation_state            ← State file của MemoryConsolidator
│
├── src/
│   ├── core/
│   │   ├── orchestrator.py         ← ReActOrchestrator, WorkerEngine, SelfCritiqueAgent
│   │   ├── semantic_interceptor.py ← Intent classification bằng cosine similarity
│   │   ├── conversation_memory.py  ← Short-term memory (sliding window 5 cặp)
│   │   └── intents.json            ← 16 intents, ~50 anchor phrases
│   │
│   ├── db/
│   │   └── hybrid_rag.py           ← QdrantManager, Neo4jManager, HybridRAG
│   │
│   ├── ui/
│   │   ├── spotlight.py            ← SpotlightWindow + 4 QThread Workers
│   │   └── voice_engine.py         ← GeminiSTT, VoiceRecorder
│   │
│   ├── utils/
│   │   ├── parser.py               ← PDFParser, PPTXParser, chunking logic
│   │   └── watchdog_listener.py    ← InboxWatcher, asyncio queue pipeline
│   │
│   └── services/
│       ├── memory_consolidator.py  ← Nightly APScheduler + Gemini Map-Reduce
│       └── docx_exporter.py        ← Xuất báo cáo Word từ RAG
│
├── Obsidian_Vault/
│   ├── 01_Inbox/                   ← Thả tài liệu vào đây
│   ├── 02_Knowledge/               ← Tài liệu đã xử lý + Markdown bóc tách
│   └── 03_Agent_Memory/
│       └── Profile.md              ← Memory consolidation
│
├── qdrant_storage/                 ← Qdrant embedded database files
├── assets/
│   └── greeting.mp3                ← Âm thanh chào khi bật Voice mode
│
└── tools/                          ← Tiện ích phát triển
    ├── view_qdrant.py              ← Xem nội dung Qdrant collection
    └── reindex.py                  ← Re-index toàn bộ Knowledge folder
```

---

## 9. Quy tắc kiến trúc cứng

*(Tóm tắt từ `ARCHITECTURE_RULES.md` — tài liệu đầy đủ 117 dòng trong repo)*

### Bất biến Main Thread
**Tuyệt đối nghiêm cấm** gọi API, I/O blocking, hay `time.sleep()` trên Main Thread (Qt Event Loop). Vi phạm → UI freeze. Mọi tác vụ nặng phải chạy trong `QThread` Worker.

### Giao tiếp giữa Thread
Workers chỉ được giao tiếp với Main Thread qua `pyqtSignal`. Không chia sẻ vùng nhớ, không sửa biến trực tiếp.

### Naming Convention
- Worker class: hậu tố `*Worker` (VoiceWorker, AIWorker...)
- Signal: tiền tố `sig_*` (sig_chunk, sig_finished...)
- Slot: tiền tố `_on_*` (_on_ai_chunk, _on_voice_finished...)
- State flag: `_is_*` hoặc `_has_*` (private)

### Zero-Dependency Law
Không được cài thêm thư viện bên thứ 3 nếu Python Standard Library giải quyết được. Bám chặt `requirements.txt`.

### Luồng Streaming (Generator)
Mọi luồng text AI phải dùng `yield` (Generator). Nghiêm cấm `return <string>` trong Generator function.

### Graceful Shutdown
Khi dừng Worker: `stop()` → `wait(3000ms)` → `terminate()` nếu vẫn kẹt. Không bao giờ bỏ mặc thread zombie.

---

## 10. Trạng thái hiện tại và hạn chế đã biết

### ✅ Hoạt động tốt
- Spotlight UI (text mode) với 3 chế độ FAST/NINJA/AI
- Voice STT + TTS (streaming)
- Qdrant vector search
- Watchdog ingest pipeline (PDF/PPTX)
- Memory consolidation nightly
- DocxExporter
- SemanticInterceptor intent classification
- ReAct orchestrator (Fast-Track + Deep-Track + DuckDuckGo web search)

### ⚠️ Technical Debt đã biết

| Vấn đề | Mức độ | Mô tả |
|--------|--------|-------|
| Neo4j/GraphRAG không hoạt động | 🔴 Critical | `watchdog_listener.py` chỉ lưu vào Qdrant, bỏ qua bước extract entities → Neo4j graph rỗng → `retrieve_context()` chỉ dùng vector search |
| ConversationMemory không vào prompt | 🔴 Critical | `conversation_memory.py` tồn tại và lưu Q&A, nhưng `_node_generate()` không đưa lịch sử vào prompt → AI không nhớ cuộc hội thoại |
| `spotlight.py` God File (1325 dòng) | 🟡 Medium | 6 class trong 1 file, khó maintain |
| Duplicate logic Orchestrator | 🟡 Medium | Fast-track và Deep-track có ~60 dòng logic RAG trùng nhau |
| Cosine search Pure Python | 🟡 Medium | `sum(a * b for a, b in zip(...))` chậm hơn numpy 10-50x |
| `PPTXParser` sleep cứng 4s/slide | 🟡 Medium | PPTX 30 slides = 120s chờ, không có exponential backoff |

### 🚧 Tính năng chưa hoàn thiện
- **GraphRAG thực sự**: Kiến trúc dual-database (Qdrant + Neo4j) đã xây dựng nhưng Neo4j chưa có dữ liệu
- **Multi-turn memory**: ConversationMemory class hoàn chỉnh nhưng chưa được inject vào prompt LLM
- **Vision Mode**: Đã quy hoạch trong ARCHITECTURE_RULES nhưng chưa implement (`src/ui/vision_worker.py`)
- **Local LLM**: Đã quy hoạch `src/services/llm_client.py` nhưng chưa implement

---

## 📌 Context nhanh cho AI khác

> Nếu bạn là AI assistant được gửi README này để tư vấn về dự án: đây là **Python project chạy trên Windows**, không phải web app. Stack chính: **PyQt6 (UI) + Gemini API + OpenRouter + Qdrant (embedded) + Neo4j (cloud)**. Kiến trúc đa luồng nghiêm ngặt theo quy tắc ARCHITECTURE_RULES.md. File quan trọng nhất: `main.py` (boot sequence), `src/core/orchestrator.py` (AI logic), `src/db/hybrid_rag.py` (database), `src/ui/spotlight.py` (UI + workers). Hai vấn đề nghiêm trọng nhất cần fix: (1) Neo4j không có dữ liệu vì bỏ qua entity extraction khi ingest, (2) ConversationMemory không được đưa vào prompt LLM.