# SỔ TAY HƯỚNG DẪN THAO TÁC TOÀN DIỆN
## DIGITAL SCHOLAR AI — PERSONAL RESEARCH COCKPIT (PHIÊN BẢN V6.0)

> **Tài liệu hướng dẫn vận hành chi tiết từ A - Z**  
> Dành cho người dùng cá nhân: Thao tác máy tính nhanh hàng ngày & Nghiên cứu học thuật chuyên sâu.

---

## MỤC LỤC
1. [Chuẩn bị & Cấu hình môi trường (.env)](#1-chuẩn-bị--cấu-hình-môi-trường-env)
2. [Khởi động & Kiểm tra hệ thống](#2-khởi-động--kiểm-tra-hệ-thống)
3. [Tương tác giọng nói tự động rảnh tay (Hands-free Voice)](#3-tương-tác-giọng-nói-tự-động-rảnh-tay-hands-free-voice)
4. [Điều khiển Desktop cá nhân hàng ngày ($0 API, <1ms)](#4-điều-khiển-desktop-cá-nhân-hàng-ngày-0-api-1ms)
5. [Quy trình nghiên cứu học thuật & Bóc tách tài liệu (Research Cockpit)](#5-quy-trình-nghiên-cứu-học-thuật--bóc-tách-tài-liệu-research-cockpit)
6. [Khai thác đối tác phản biện Socratic & Nhật ký nghiên cứu (Obsidian)](#6-khai-thác-đối-tác-phản-biện-socratic--nhật-ký-nghiên-cứu-obsidian)
7. [Xử lý sự cố thường gặp (Troubleshooting) & Thoát an toàn](#7-xử-lý-sự-cố-thường-gặp-troubleshooting--thoát-an-toàn)

---

## 1. CHUẨN BỊ & CẤU HÌNH MÔI TRƯỜNG (.ENV)

Trước khi chạy, bạn kiểm tra file `.env` tại thư mục gốc `agent_nckh/`:

```ini
# --- API Keys cốt lõi ---
GEMINI_API_KEY=AIzaSy...              # Key Gemini Direct (Google AI Studio)
OPENROUTER_API_KEY=sk-or-v1-...       # Key OpenRouter (dùng cho model suy luận sâu)

# --- Cơ chế Giọng Nói ---
VOICE_MODE=vad                        # vad: Tự động rảnh tay (khuyên dùng) | ptt: Giữ phím để nói
GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview

# --- Cơ sở dữ liệu Tri thức ---
NEO4J_URI=neo4j+s://xxxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
OBSIDIAN_VAULT_PATH=C:\Users\luuth\Desktop\agent_nckh\Obsidian_Vault

# --- Cấu hình Mô hình ---
WORKER_MODEL=google/gemini-2.5-pro
```

> [!TIP]
> **Cơ chế Failover bảo vệ chi phí:** Hệ thống có sẵn `FailoverLLMClient`. Nếu OpenRouter của bạn cạn tiền hoặc bị lỗi 403/429, hệ thống sẽ tự động chuyển sang gọi trực tiếp qua `GEMINI_API_KEY` (Gemini 2.5 Flash) nên bạn không bao giờ lo bị đứt đoạn công việc.

---

## 2. KHỞI ĐỘNG & KIỂM TRA HỆ THỐNG

### Bước 1: Kích hoạt môi trường ảo
Mở PowerShell tại thư mục `agent_nckh`:
```powershell
.\venv\Scripts\activate
```
*(Khi thấy chữ `(venv)` màu xanh ở đầu dòng lệnh là đã thành công).*

### Bước 2: Chạy kiểm thử tự động (Architecture Police & Tests)
Trước khi khởi chạy, bạn có thể chạy script kiểm tra:
```powershell
python production_check.py
```
*Kết quả kỳ vọng:* Toàn bộ AST Linter đạt **0 FAIL** và vượt qua **51/51 dynamic integration tests**.

### Bước 3: Khởi chạy Agent nền (Background Daemon)
```powershell
python main.py
```
*Dấu hiệu nhận biết hệ thống đã sẵn sàng:*
- Terminal xuất hiện log: `[Main] HybridRAG đã sẵn sàng`, `[VoiceRecorder] Silero VAD ONNX sẵn sàng`.
- Xuất hiện một biểu tượng AI nhỏ ở góc phải khay hệ thống (System Tray cạnh đồng hồ Windows).

---

## 3. TƯƠNG TÁC GIỌNG NÓI TỰ ĐỘNG RẢNH TAY (HANDS-FREE VOICE)

Hệ thống được tích hợp **Silero VAD v6 (ONNX)** chạy trực tiếp trên CPU, mang lại trải nghiệm thoại hoàn toàn tự nhiên:

```
[ Bấm Alt + Space 1 lần ] 
       ↓
[ Bạn nói tự nhiên (Có 500ms Pre-buffer bảo toàn chữ đầu) ]
       ↓
[ Bạn ngừng nói > 1.5 giây (Trailing Silence) ]
       ↓
[ Tự động gửi âm thanh lên Gemini STT -> Thực thi ngay lập tức ]
```

### Các ưu điểm vượt trội:
1. **Không cần giữ phím:** Bạn chỉ cần bấm `Alt + Space` 1 lần để mở mic, sau đó nói bình thường.
2. **Không bị mất âm đầu:** Nhờ bộ đệm **500ms Pre-speech Ring Buffer**, dù bạn bắt đầu nói ngay lập tức thì các phụ âm đầu câu ("Mở...", "Bật...", "Cho...") vẫn được thu trọn vẹn.
3. **Chống ồn quạt & bàn phím:** Tiếng gõ phím cơ hay tiếng quạt gió không kích hoạt mic ảo như thuật toán RMS cũ.

---

## 4. ĐIỀU KHIỂN DESKTOP CÁ NHÂN HÀNG NGÀY ($0 API, <1MS)

Nhờ bộ lọc **`HybridIntentSniffer` và Vietnamese Stopword Stripper**, bạn có thể nói chuyện bằng văn nói tiếng Việt thông thường, chứa nhiều từ đệm rác mà Agent vẫn bóc tách chính xác:

| Nhu cầu thao tác | Bạn có thể nói tự nhiên (Voice) | Hành động thực tế của Agent | Độ trễ | Chi phí |
| :--- | :--- | :--- | :---: | :---: |
| **Mở YouTube theo bài** | *"Ờ... mở giùm tao cái... bài gì của Sơn Tùng ấy trên YouTube đi"* | Lọc sạch thành query `'Sơn Tùng'` $\rightarrow$ mở đúng bài trên YouTube | < 20ms | **$0** |
| **Mở trang chủ YouTube**| *"Ê mở YouTube coi"* | Mở trang chủ `https://www.youtube.com` | < 10ms | **$0** |
| **Hỏi lại khi slot rỗng**| *"Phát bài hát coi"* (chưa có tên bài) | Phản hồi lại: *"Bạn muốn mở bài hát hoặc video gì trên YouTube?"* | < 5ms | **$0** |
| **Tắt tiếng hệ thống** | *"Tắt tiếng giùm tao với"* / *"Mute âm thanh đi"* | Windows tắt tiếng ngay lập tức | < 5ms | **$0** |
| **Chỉnh mức âm lượng** | *"Chỉnh âm lượng 65% nhé"* / *"Cho to lên tí"* | Đặt âm lượng hệ thống chuẩn xác | < 5ms | **$0** |
| **Mở ứng dụng làm việc**| *"Bật giùm anh VS Code cái"* / *"Mở Chrome đi"* | Khởi chạy VS Code / Google Chrome | < 30ms | **$0** |
| **Tra cứu thời gian** | *"Bây giờ là mấy giờ rồi"* / *"Hôm nay thứ mấy"* | Đọc to và hiện thông tin ngày giờ | < 5ms | **$0** |
| **Sao chép câu trả lời**| *"Copy câu vừa rồi"* | Lưu câu trả lời trước đó vào Clipboard | < 5ms | **$0** |

---

## 5. QUY TRÌNH NGHIÊN CỨU HỌC THUẬT & BÓC TÁCH TÀI LIỆU (RESEARCH COCKPIT)

### 5.1. Nạp tài liệu tự động (Cơ chế Dual-Write)
1. Bạn tải bài báo khoa học mới (PDF hoặc slide PPTX).
2. Kéo thả file vào thư mục:  
   📂 `Obsidian_Vault/01_Inbox/`
3. **Hệ thống ngầm tự động thực hiện 4 bước ($0 API):**
   - **Bóc tách cấu trúc C5:** Phân loại Heading (Abstract, Introduction, Methodology, Experiments...) bằng font size PyMuPDF.
   - **Gắn prefix ngữ cảnh:** Mỗi đoạn văn được gán nhãn: `[Tên file | Section | Trang]`.
   - **Lưu Qdrant Vector DB:** Lưu trữ dense vectors cho tìm kiếm ngữ nghĩa.
   - **Dựng cây Neo4j Graph:** Dựng khung xương tài liệu `(:Paper)-[:HAS_SECTION]->(:Section)-[:HAS_CHUNK]->(:Chunk)`.
   - **Lưu trữ Obsidian:** Kết xuất file Markdown sang thư mục `02_Knowledge/` và di chuyển file gốc an toàn.

> [!NOTE]
> **Giải quyết dứt điểm Bẫy tái chỉ mục (Re-indexing Trap):** Nhờ cây Neo4j được dựng ngay từ đầu kèm `qdrant_chunk_ids`, sau này khi bạn có 200 bài báo và muốn mở rộng đồ thị quan hệ ngữ nghĩa sâu, hệ thống chỉ cần đọc text từ Qdrant/SQLite để thêm cạnh mà **không phải parse lại file PDF từ đầu**.

---

## 6. KHAI THÁC ĐỐI TÁC PHẢN BIỆN SOCRATIC & NHẬT KÝ NGHIÊN CỨU (OBSIDIAN)

Hệ thống được thiết kế theo đúng triết lý: *"Không phải AI suy nghĩ thay tôi, mà là cùng tôi phân tích để mò ra các điểm nghẽn và giả định ngầm"*.

### 6.1. Nhận gợi ý phản biện Socratic trong Spotlight
- Bấm `Ctrl + Space` (hoặc `Alt + Space`), nhập câu hỏi nghiên cứu:
  > *"Cho tôi biết cơ chế cập nhật của GraphRAG trong môi trường dynamic graph."*
- Agent tổng hợp tài liệu từ Qdrant + Neo4j, sinh câu trả lời và tự động chêm thêm **Gợi ý phản biện**:
  > **💡 Gợi ý phản biện học thuật (Socratic Thought Partner):**  
  > *- Phương pháp trên có phụ thuộc vào giả định ngầm nào không (ví dụ: cấu trúc đồ thị tĩnh, tài nguyên RAM/VRAM, phân phối IID)?*  
  > *- Nếu áp dụng vào bài toán thực tế của bạn, điểm nghẽn (bottleneck) lớn nhất có thể nằm ở bước nào?*

### 6.2. Kiểm tra Nhật ký nghiên cứu (Research Journal)
Mỗi ngày khi bạn nghiên cứu, toàn bộ các phát hiện về lỗ hổng, giả định và điểm nghẽn sẽ được lưu trữ tự động tại:
📂 `Obsidian_Vault/05_Research_Journal/YYYY-MM-DD.md`

**Cấu trúc mẫu của một ghi chép trong file:**
```markdown
### [14:25:30] GraphRAG Scalability Study
- **Vấn đề / Điểm nghẽn:** Dynamic edge updates cause linear re-embedding overhead
- **Giả định / Rủi ro:** Memory thrashing on graphs with > 1M edges
- **Tags:** #GraphRAG #NCKH #Benchmark
---
```
Bạn chỉ cần mở Obsidian lên là có ngay bức tranh tổng hợp các điểm nghẽn học thuật tích lũy theo thời gian.

---

## 7. XỬ LÝ SỰ CỐ THƯỜNG GẶP (TROUBLESHOOTING) & THOÁT AN TOÀN

### 7.1. Bảng xử lý sự cố nhanh

| Hiện tượng | Nguyên nhân | Cách khắc phục |
| :--- | :--- | :--- |
| **Phím tắt `Alt+Space` không nhận** | Windows cần quyền Administrator để bắt hotkey | Chuột phải vào Terminal $\rightarrow$ Chọn **Run as Administrator** rồi chạy lại `python main.py`. |
| **Lỗi cạn quota OpenRouter (402/403)** | Hết tiền hoặc chạm rate limit | **Yên tâm:** `FailoverLLMClient` đã tự động chuyển sang Gemini Flash Direct mà không làm gián đoạn câu trả lời. |
| **Micro không nhận giọng** | Chưa cắm mic hoặc Windows chặn quyền mic | Vào Windows Settings $\rightarrow$ Privacy & Security $\rightarrow$ Microphone $\rightarrow$ Bật quyền cho Desktop Apps. |
| **Neo4j báo ngắt kết nối** | Mạng chập chờn hoặc hết hạn Aura | Hệ thống tự động **Graceful Degradation** chuyển sang dùng 100% Vector Qdrant, ứng dụng **không bị crash**. |

### 7.2. Thoát ứng dụng an toàn
Agent chạy ngầm dạng Daemon, khi muốn đóng:
1. **Cách 1 (Khuyên dùng):** Click chuột phải vào Icon AI ở khay hệ thống (System Tray) $\rightarrow$ Chọn **Quit**.
2. **Cách 2:** Bấm `Ctrl + C` tại cửa sổ Terminal đang chạy `main.py`.
3. Hệ thống sẽ tự động thực hiện tiến trình **Cleanup**: Giải phóng phím tắt toàn cục, đóng an toàn kết nối Qdrant/Neo4j và xả RAM sạch sẽ.
