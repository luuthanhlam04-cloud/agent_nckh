# **BẢN ĐẶC TẢ KIẾN TRÚC TOÀN DIỆN: DIGITAL SCHOLAR (AGENT V5.0)**

*Tài liệu Hợp nhất Kiến trúc Nền tảng, Quy trình Xử lý Đa tầng, Quản trị Đa luồng (Multi-threading) và Tương tác Giọng nói (Voice Mode).*

# **PHẦN 1: TỔNG QUAN HỆ THỐNG VÀ CHIẾN LƯỢC PHÁT TRIỂN**

Tài liệu Agent V5.0 xác lập toàn bộ thiết kế kiến trúc phần mềm, mô hình dữ liệu và các quy trình xử lý ngoại lệ cho dự án **Digital Scholar**. Ở phiên bản V5.0, hệ thống đã hoàn thiện luồng **Tương tác Giọng nói (Voice-STT)** và kiến trúc **Đánh chặn Hybrid (Regex + LLM)** với độ ổn định tuyệt đối (Vượt 100% bài test Production).

Hệ thống vận hành dưới dạng một Local Background Daemon (Tiến trình chạy ngầm) kết hợp LLM đám mây thương mại nhằm cung cấp Trợ lý Ảo đa năng hỗ trợ Nghiên cứu Khoa học và tự động hóa tác vụ OS. 

| Hạng mục đặc tả | Định hướng triển khai Production |
| :---- | :---- |
| **Tên mã dự án** | Digital Scholar - Hybrid Voice Agent |
| **Phiên bản / Giai đoạn** | Agent V5.0 - Nâng cấp toàn diện Mô hình AI (Embedding & Voice) và Kiến trúc cốt lõi. |
| **Mục tiêu cốt lõi** | **1. Nghiên cứu khoa học (GraphRAG kép):** Kiến tạo sơ đồ tri thức qua đồ thị thực thể (Neo4j) và tìm kiếm tương đồng vector bằng mô hình `multilingual-e5-base` (Qdrant Local). <br>**2. Trí nhớ phân tầng:** Obsidian (Dài hạn), Cửa sổ trượt N=5 (Ngắn hạn). <br>**3. Tối ưu chi phí & Tốc độ (Hybrid Architecture):** Lớp lọc Regex cục bộ xử lý lệnh hệ thống (Mở YouTube, Copy, Bật nhạc, Tra giờ) trong **0 giây** không tốn API. <br>**4. Tương tác Giọng nói cục bộ:** STT **Whisper-small** (tối ưu hóa độ chuẩn xác Tiếng Việt) kết hợp TTS (Azure) phản hồi bằng luồng âm thanh tự nhiên. |
| **Đối tượng sử dụng** | Nhà nghiên cứu, sinh viên cần công cụ quản lý tri thức bảo mật cục bộ + Trợ lý máy tính điều khiển bằng giọng nói. |
| **Chiến lược phát triển** | **- Định tuyến Đa mô hình:** **Gemini 3.1 Flash Lite** làm lõi phân loại siêu tốc; **Gemini 2.5 Pro (via OpenRouter)** làm bộ xử lý RAG hạng nặng.<br>**- Giao diện Tàng hình (Spotlight):** Popup mờ Mica (Win11), gọi bằng `Ctrl+Space` (Text) hoặc `Ctrl+Shift+Space` (Voice), tự ẩn khi xong việc. |

## **1.1. Yêu cầu hệ thống (System Requirements)**

* **Hệ điều hành:** Windows 11 (Bắt buộc để hỗ trợ hiệu ứng Mica UI và `win11toast`).
* **Môi trường thực thực:** Python 3.11.9.
* **Bộ nhớ RAM:** Tối thiểu 8GB (Tối ưu sử dụng RAM nhờ cơ chế Singleton và giải phóng bộ nhớ tự động).
* **Công cụ bổ trợ (Bắt buộc cho Voice):** `ffmpeg` để Whisper xử lý âm thanh. 

---

# **PHẦN 2: KIẾN TRÚC HỆ THỐNG TỔNG THỂ (SYSTEM ARCHITECTURE)**

Hệ thống tuân thủ thiết kế module hóa phân rã theo 5 tầng chức năng, được bảo vệ nghiêm ngặt bằng kiến trúc xử lý Đa luồng (Multi-threading) an toàn:

## **2.1. Tầng Giao diện & Trải nghiệm (UI/UX - Frontend cục bộ)**

* **Nền tảng:** PyQt6 (Windows 11 Mica).  
* **Cửa sổ lệnh Spotlight UI:** Không viền, bo góc, luôn nổi (Always on Top).
* **3 Chế độ Hiển thị Động:**
  * `NINJA Mode`: Chạy ngầm lập tức, không hiện UI (Dùng cho lệnh mở YouTube, Copy). Trả kết quả qua Windows Toast Notification.
  * `FAST Mode`: Giữ cửa sổ nhỏ gọn, hiện kết quả text/voice tức thì (Tra cứu ngày, giờ).
  * `AI Mode`: Mở rộng khung UI, hiển thị "Đang suy nghĩ..." khi giao tiếp với LLM.
* **Tương tác Giọng nói (Voice):** Bấm `Ctrl+Shift+Space`. Hệ thống thu âm qua PyAudio, tự động tắt mic khi nhả phím và phản hồi bằng giọng nói.

## **2.2. Tầng Bộ não xử lý Đa luồng (Multi-Threading Core)**

* **Main Thread (Event Loop):** Chỉ xử lý đồ họa (Vẽ UI). Tuyệt đối không gọi API ở đây.
* **QThread Workers:** Các tác vụ nặng (`AIWorker`, `TTSWorker`, `VoiceWorker`) được cô lập ở luồng phụ. Giao tiếp với Main UI qua `pyqtSignal`.
* **Quản trị vòng đời C++ / Python:** Dọn dẹp Worker an toàn bằng vòng lặp `try-except RuntimeError` khi chặn các đối tượng C++ bị hủy (`deleteLater`).
* **Thread-safe Singleton:** Mô hình Whisper (STT) được bọc bằng `threading.Lock`, ngăn chặn nạp bộ nhớ chồng chéo.

## **2.3. Tầng AI & Logic chuyên sâu (Core Engine)**

* **Bộ Đánh chặn Hybrid (Regex Interceptor):** Chặn các lệnh hệ điều hành trước khi gửi lên API. Nếu Regex thất bại, tự động chuyển xuống LLM để sửa lỗi phát âm (Fuzzy logic).
* **Nhận diện giọng nói (Whisper Local):** Đã nâng cấp lên phiên bản **Whisper `small`** giúp nhận diện tiếng Việt cực kỳ chính xác.
* **Xử lý Ngôn ngữ (LLM):** Sử dụng LLM để sinh kết quả từ đồ thị tri thức (GraphRAG) thông qua kiến trúc Pipeline độc lập.

## **2.4. Tầng Dữ liệu & Hạ tầng (Data & Storage - Nâng cấp V5.0)**

Đặc điểm nổi bật nhất của bản V5.0 là hệ thống RAG Hybrid kết hợp Semantic Search (Vector) và Knowledge Graph (Đồ thị tri thức):

| Thành phần dữ liệu | Nền tảng lưu trữ | Cơ sở kỹ thuật |
| :---- | :---- | :---- |
| **Long-term Memory** | **Obsidian Vault** | Lưu trữ Markdown an toàn cục bộ. |
| **Vector Database** | **Qdrant (Local)** | Sử dụng model `intfloat/multilingual-e5-base` (768 dimensions). Tự động phân loại `query:` và `passage:` chuẩn hóa theo asymetric search. Có trang bị **Guardrail an toàn** tự động xóa (Format) CSDL cũ nếu phát hiện kích thước vector bị thay đổi để bảo vệ hệ thống khỏi lỗi Crash. |
| **Chunking Logic** | **Parser Algorithm** | Bắt buộc chia nhỏ văn bản (PDF/PPTX) với **Max tokens = 500** (~2000 kí tự) và gối đầu chồng chéo **Overlap = 100 tokens** để duy trì ngữ cảnh toàn diện. |
| **Graph Database** | **Neo4j Cloud** | Truy vấn thực thể từ xa (Aura Free Tier). |

---

# **PHẦN 3: HƯỚNG DẪN CÀI ĐẶT VÀ TRIỂN KHAI**

## **3.1. Thiết lập tệp tin môi trường (.env)**
Tạo file `.env` tại thư mục gốc:
```env
GEMINI_API_KEY="Khoa_api_gemini_chinh"  
OPENROUTER_API_KEY="Khoa_openrouter"  
NEO4J_URI="neo4j+ssc://xxx.databases.neo4j.io" 
NEO4J_USER="neo4j"  
NEO4J_PASSWORD="Mat_khau_database_cloud"  
OBSIDIAN_VAULT_PATH="C:/Users/Ten_Nguoi_Dung/Documents/Obsidian_Vault"
```

## **3.2. Triển khai**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
*(Cần cài đặt `ffmpeg` hệ thống để Voice STT hoạt động).*

---

# **PHẦN 4: TIÊU CHUẨN CODE (ZERO TECHNICAL DEBT)**

Toàn bộ hệ thống hiện tại được duy trì bởi kịch bản kiểm thử tĩnh và động thông qua tệp `production_check.py` (Pass 50/50 Test Cases) trước mọi lượt Commit, đảm bảo tính bền vững lâu dài. Hệ thống áp dụng nghiêm ngặt nguyên lý kiến trúc SOLID, quản trị bộ nhớ tự động và chống gián đoạn tác vụ ở mọi tầng (Self-healing).

--- *Hết tài liệu Đặc tả Kiến trúc Digital Scholar (Agent V5.0)* ---