# **BẢN ĐẶC TẢ KIẾN TRÚC TOÀN DIỆN: DIGITAL SCHOLAR (AGENT V4.0)**

*Tài liệu Hợp nhất Kiến trúc Nền tảng, Quy trình Xử lý Đa tầng và Quản trị Rủi ro Production*

# **PHẦN 1: TỔNG QUAN HỆ THỐNG VÀ CHIẾN LƯỢC PHÁT TRIỂN**

Tài liệu Agent V4.0 xác lập toàn bộ thiết kế kiến trúc phần mềm, mô hình dữ liệu và các quy trình xử lý ngoại lệ cho dự án **Digital Scholar**. Hệ thống vận hành dưới dạng một Local Background Daemon (Tiến trình chạy ngầm hệ điều hành) kết hợp các mô hình ngôn ngữ lớn (LLM) đám mây thương mại nhằm cung cấp một Trợ lý Ảo đa năng hỗ trợ Nghiên cứu Khoa học chuyên sâu và tự động hóa tác vụ.  
Hệ thống được thiết kế đặc thù nhằm giải quyết bài toán giới hạn phần cứng của người dùng (tối ưu cho thiết bị có khoảng 5.7-7.7 GB RAM trống), đồng thời giảm thiểu hiện tượng ảo giác (hallucination) và tối ưu hóa chi phí API thông qua cơ chế lai (Hybrid Architecture).

| Hạng mục đặc tả | Định hướng triển khai Production |
| :---- | :---- |
| **Tên mã dự án** | Digital Scholar - Hybrid Research Agent |
| **Phiên bản / Giai đoạn** | Agent V4.0 - Đóng gói kiến trúc và hợp nhất mã nguồn Production Ready. |
| **Mục tiêu cốt lõi (Core Value)** | **1. Nghiên cứu khoa học chuyên sâu (GraphRAG kép):** Tự động bóc tách tài liệu đa định dạng, kiến tạo sơ đồ tri thức qua đồ thị thực thể (Neo4j Cloud) kết hợp tìm kiếm tương đồng vector (Qdrant Local) nhằm giảm tải JVM và hạn chế ảo giác thông tin. <br>**2. Trí nhớ phân tầng bảo mật:** Hệ thống quản trị trí nhớ dài hạn lưu tại Obsidian, trí nhớ ngắn hạn hoạt động bằng thuật toán cửa sổ trượt (Sliding Window N=5) giúp tiết kiệm token, trí nhớ ngầm định gom nhóm bằng Map-Reduce. <br>**3. Tối ưu chi phí API:** Xây dựng lớp lọc Regex cục bộ xử lý 60% lệnh hệ thống và tác vụ cơ bản mà không cần gọi LLM đám mây. <br>**4. Tối ưu hóa tài nguyên phần cứng:** Hệ thống chạy ngầm tiêu tốn dưới 100MB RAM, giải mã giọng nói (STT Whisper-tiny) tối ưu chạy trên NPU (Intel AI Boost). |
| **Đối tượng sử dụng** | Nhà nghiên cứu khoa học, sinh viên đại học/sau đại học cần một công cụ quản lý tri thức bảo mật dữ liệu cục bộ kết hợp năng lực xử lý của các mô hình LLM tiên tiến. |
| **Chiến lược phát triển** | **- Kiến trúc xử lý đa mô hình:** Sử dụng **Google Gemini 2.5 Flash (Free Tier)** làm bộ định tuyến ý định tốc độ cao; và chuyển giao các tác vụ suy luận phức tạp (RAG, viết code, bóc tách PDF) cho cổng **OpenRouter (Pay-as-you-go)** nhằm tận dụng năng lực phân tích cao cấp và giảm thiểu lỗi giới hạn tần suất (Rate Limit). <br>**- Giao diện tối giản:** Cửa sổ lệnh dạng popup, xuất hiện qua phím tắt và ẩn đi ngay sau khi nhận lệnh. Phản hồi chủ yếu qua luồng âm thanh Text-to-Speech. <br>**- Tự động sửa lỗi JSON:** Khắc phục lỗi định dạng dữ liệu đầu ra của LLM thông qua cơ chế Auto-Correction Loop kết hợp Pydantic Validation. |

## **1.1. Yêu cầu hệ thống (System Requirements)**

Nhằm đảm bảo hiệu năng tối ưu cho luồng xử lý Agent nền và các tác vụ đồ họa, môi trường triển khai cần đáp ứng:
* **Hệ điều hành:** Windows 11 (Bắt buộc để hỗ trợ hiệu ứng Mica UI và `win11toast`).
* **Môi trường thực thi:** Python 3.11.9.
* **Bộ nhớ RAM:** Khuyến nghị thiết bị có tối thiểu 8GB RAM (Cần khoảng trống khả dụng từ 5.7 - 7.7 GB để vận hành trơn tru).
* **Phần mềm bên thứ ba:** Obsidian (để quản lý Vault Memory), Trình duyệt Google Chrome/Edge.
* **Công cụ bổ trợ (Bắt buộc cho STT Whisper):** Cần cài đặt `ffmpeg` (Gõ lệnh `winget install Gyan.FFmpeg` vào Terminal và khởi động lại Terminal).

# **PHẦN 2: KIẾN TRÚC HỆ THỐNG TỔNG THỂ (SYSTEM ARCHITECTURE)**

Hệ thống tuân thủ thiết kế module hóa phân rã theo 5 tầng chức năng:

## **2.1. Tầng Giao diện & Trải nghiệm (UI/UX - Frontend cục bộ)**

* **Nền tảng phát triển:** Ứng dụng native sử dụng thư viện PyQt6 hoặc PySide6 tối ưu trên Windows 11.  
* **Cửa sổ lệnh Spotlight UI:** Thiết kế thanh nhập liệu tối giản, hỗ trợ hiệu ứng làm mờ Mica của hệ điều hành.  
* **Luồng tương tác:**  
  * *Chế độ Text Mode:* Nhấn phím tắt (Double Enter) -> Hiển thị thanh Spotlight chờ nhập văn bản. Sau khi ấn Enter, giao diện tự động ẩn và xóa bộ đệm.  
  * *Chế độ Voice Mode:* Nhấn phím tắt kèm giữ phím Space -> Kích hoạt ghi âm microphone, hiển thị biểu đồ sóng âm. Khi nhả phím Space, giao diện ẩn và tệp âm thanh được gửi đi xử lý.  
* **Phản hồi giọng nói (TTS Engine):** Sử dụng thư viện edge-tts với máy chủ Azure. Phản hồi âm thanh dạng luồng (Streaming), bắt đầu phát âm thanh ngay khi nhận những chuỗi văn bản đầu tiên từ LLM, giảm thiểu tài nguyên tiêu thụ.

## **2.2. Tầng Bộ não xử lý (Local Backend & OS Controller)**

* **Phương thức hoạt động:** Tiến trình Daemon chạy ngầm bằng Python 3.11.9, tối ưu dung lượng RAM dưới 100MB ở trạng thái chờ.  
* **Xử lý bất đồng bộ đa luồng:**  
  * `asyncio`: Quản lý hàng đợi tác vụ (Task Queue), đảm bảo sự liền mạch giữa hội thoại và nạp tài liệu ngầm.  
  * `watchdog`: Giám sát thư mục `01_Inbox/` để tự động xử lý tài liệu mới.  
  * `APScheduler`: Lập lịch tác vụ cục bộ, củng cố bộ nhớ dài hạn định kỳ vào nửa đêm.  
* **Công cụ tương tác hệ điều hành (OS Tools):**  
  * `Playwright`: Khởi chạy và điều khiển trình duyệt ngầm để truy xuất nội dung HTML.  
  * `python-docx`: Tổng hợp tri thức từ hệ thống RAG và kết xuất văn bản báo cáo khoa học.  
  * `Google Workspace API`: Tích hợp OAuth 2.0 để trích xuất dữ liệu lịch Google Calendar và Gmail.

## **2.3. Tầng AI & Logic chuyên sâu (Core Engine)**

* **Bộ định tuyến ý định (Semantic Router):** Sử dụng Gemini 2.5 Flash API (thông qua SDK `google-genai`) để nhận diện và định dạng ý định người dùng thành JSON.  
* **Động cơ suy luận chính (Worker):** Sử dụng thư viện `openai` trỏ đến OpenRouter API. Cấu hình gọi các mô hình thương mại (như `google/gemini-2.5-pro` hoặc `anthropic/claude-3.5-sonnet`) để xử lý văn bản quy mô lớn từ GraphRAG.   
* **Máy trạng thái ReAct (ReAct State Machine):** Quản lý luồng xử lý đa bước tương thích kiến trúc LangGraph nhưng hoạt động độc lập không phụ thuộc thư viện (Zero-dependency). Tích hợp cơ chế tự đánh giá (Self-Critique); tự động gọi DuckDuckGo API bổ sung ngữ cảnh web nếu thông tin nội bộ không đạt ngưỡng đánh giá.
* **Động cơ nhận diện giọng nói (STT Engine):** Triển khai Whisper-tiny biên dịch qua OpenVINO để chạy trực tiếp trên NPU, giảm tải xử lý cho CPU.  
* **Bộ phân tách tài liệu học thuật (Parsing & Chunking):** Kết hợp Marker và PyMuPDF chuyển đổi PDF sang Markdown. Gemini Vision API đọc nội dung slide PPTX, tích hợp cơ chế hoãn nhịp (time.sleep) để chống Rate Limit. Áp dụng chiến lược chia đoạn (Chunking) theo ranh giới ngữ nghĩa đoạn văn.

## **2.4. Tầng Dữ liệu & Hạ tầng (Data & Storage)**

Bảng phân tích hạ tầng lưu trữ nhằm tối ưu tài nguyên máy tính cá nhân:

| Thành phần dữ liệu | Nền tảng lưu trữ | Cơ sở kỹ thuật |
| :---- | :---- | :---- |
| **Long-term Memory** | **Obsidian Vault (Local Markdown)** | Lưu trữ gốc văn bản thuần trên máy tính người dùng, không đồng bộ thô lên đám mây nhằm bảo mật thông tin. |
| **Vector Database** | **Qdrant (Local Embedded Mode)** | Cơ sở dữ liệu Vector lõi Rust tích hợp trực tiếp, ghi dữ liệu vào ổ cứng NVMe nội bộ, ngăn ngừa rò rỉ bộ nhớ (Memory Leak). |
| **Graph Database** | **Neo4j Cloud (Aura Free Tier)** | Đẩy dữ liệu đồ thị lên nền tảng đám mây để giảm tải cho môi trường JVM cục bộ. Sử dụng giao thức `neo4j+ssc://` nhằm vượt qua lỗi chứng chỉ SSL trên Windows. |
| **Embedding Model** | **MiniLM-L12-v2 (Native Python Venv)** | Triển khai mô hình nhúng trực tiếp trên môi trường ảo (venv), tối ưu RAM dưới 1GB, hỗ trợ phân tích văn bản đa ngôn ngữ nội bộ. |

## **2.5. Tầng Công cụ Phụ trợ & Hướng dẫn (Utilities & Docs)**

* **Bảo vệ hệ thống (API Test):** Tệp `test_keys.py` cung cấp cơ chế Health Check độc lập để kiểm tra kết nối API cốt lõi (Gemini, OpenRouter, Neo4j) trước khi chạy dự án.
* **Cẩm nang vận hành:** Tài liệu `Huong_Dan_Su_Dung.md` hướng dẫn chi tiết khởi chạy nền, kiểm thử tính năng cục bộ và quy trình tắt hệ thống an toàn.

# **PHẦN 3: CHI TIẾT LUỒNG TÍNH NĂNG VÀ LOGIC XỬ LÝ (PIPELINES)**

Hệ thống được cấu trúc dựa trên vòng đời của 8 tính năng lõi:

## **Chức năng 1: Nhận diện đa phương thức (Text/Voice Activation)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành |
| :---- | :---- |
| **Bối cảnh vận hành** | Theo dõi phím tắt toàn cục trên Windows, hiển thị giao diện nhập liệu mờ Mica và phân biệt luồng Text/Voice. |
| **Trạng thái Dữ liệu** | Input: Sự kiện phím / Luồng âm thanh từ Microphone -> Output: Chuỗi văn bản (String). |
| **Chỉ tiêu hiệu năng** | Thời gian giải mã Whisper STT trên NPU < 200ms; giao diện ẩn dưới 16ms sau khi nhận lệnh. |
| **Phản hồi** | Trả kết quả âm thanh trực tiếp qua tai nghe bằng thư viện edge-tts. Không duy trì lịch sử chat trên giao diện pop-up. |

## **Chức năng 2: Bộ lọc Regex cục bộ (Zero-Cost Interceptor)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành |
| :---- | :---- |
| **Bối cảnh vận hành** | Đánh chặn các lệnh điều khiển thông thường tại `main.py` để xử lý cục bộ, giảm thiểu sử dụng API bên ngoài. |
| **Trạng thái Dữ liệu** | Input: Văn bản -> Output: Mã Python thực thi chức năng tương ứng / Chuyển tiếp tới LLM. |
| **Triển khai tiêu biểu** | Lệnh sao chép văn bản (copy vào Clipboard) và hiển thị thông báo Notification (Windows Toast) để hỗ trợ thao tác nhanh. |

*(Ví dụ mã nguồn: Nhận diện các lệnh mở ứng dụng, tra cứu thời gian, yêu cầu kết xuất tài liệu, lưu thông tin ghi chú vào Obsidian...)*

## **Chức năng 3: Bộ định tuyến ý định dựa trên ngữ nghĩa (Semantic Router)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành |
| :---- | :---- |
| **Bối cảnh vận hành** | Nhận diện ý định phức tạp và định tuyến các luồng RAG theo chủ đề. |
| **Trạng thái Dữ liệu** | Input: Câu hỏi người dùng + Ngữ cảnh N=5 -> Output: JSON chuẩn hóa cấu trúc qua Pydantic. |
| **Chỉ tiêu hiệu năng** | Thời gian phân loại qua Gemini Flash API < 500ms. Kết xuất JSON chính xác nhờ thiết lập chế độ Structured Output. |

*Luồng xử lý:* Nối lịch sử hội thoại vào câu truy vấn mới, gửi yêu cầu định dạng JSON qua Gemini Flash để trích xuất các thông tin ngữ cảnh, sau đó phân tách và kích hoạt luồng tính toán phù hợp.

## **Chức năng 4: Luồng trích xuất đồ thị tri thức (Auto-GraphRAG Ingestion)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành |
| :---- | :---- |
| **Bối cảnh vận hành** | Quét ngầm thư mục, chuyển hóa tài liệu PDF/PPTX thành dữ liệu đồ thị và vector. |
| **Trạng thái Dữ liệu** | Input: Tệp tin tài liệu cục bộ -> Output: Nút/Cạnh đồ thị tại Neo4j + Vector tại Qdrant. |

*Luồng xử lý:* `watchdog` bắt sự kiện tệp mới, gọi bộ phân tích (parser) chuyển đổi tài liệu sang Markdown. Mô hình LLM bóc tách các thực thể và mối quan hệ để tạo câu lệnh Cypher nạp vào Neo4j. Đồng thời, văn bản được băm (chunk) và nhúng vector vào Qdrant. ID của chunk được lưu trên thuộc tính nút Neo4j để đồng bộ dữ liệu đồ thị và vector.

## **Chức năng 5: Truy xuất đa ngôn ngữ và lai kép (Hybrid RAG)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành |
| :---- | :---- |
| **Bối cảnh vận hành** | Truy vấn chéo ngôn ngữ (ví dụ: người dùng hỏi tiếng Việt, tài liệu nguồn tiếng Anh) dựa trên mô hình nhúng lai. |
| **Bản chất kỹ thuật** | Sử dụng mô hình nhúng đa ngôn ngữ `MiniLM-multilingual` để tính khoảng cách Cosine, đối chiếu các cụm từ ngữ nghĩa xuyên ngôn ngữ. |

*Luồng xử lý:* Từ khóa được chuyển ngữ thành tiếng Anh, hệ thống sử dụng thuật toán quét Neo4j để lấy ID chunk liên quan, sau đó truy xuất nội dung gốc từ kho Qdrant cục bộ. Khối văn bản chuyên ngành tiếng Anh sẽ được đẩy vào mô hình sinh văn bản để phân tích và trả về bằng ngôn ngữ mong muốn của người dùng.

## **Chức năng 6: Đánh giá chất lượng và Luồng ReAct (Critique Loop)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành |
| :---- | :---- |
| **Bối cảnh vận hành** | Đánh giá dữ liệu nội bộ được thu thập (LLM-as-a-judge) tích hợp cùng Máy trạng thái ReAct (ReAct State Machine). |
| **Trạng thái Dữ liệu** | Input: Ngữ cảnh từ RAG -> Output: Điểm đánh giá dạng JSON -> Quyết định tổng hợp nội dung hay tra cứu mở rộng. |

*Luồng xử lý:* Phân tích đánh giá ngữ cảnh thu thập với câu hỏi gốc. Nếu điểm tin cậy đạt yêu cầu, tiến hành trả lời; nếu nội dung thiếu hụt, kích hoạt API tra cứu thông tin trên môi trường Web để bổ sung trước khi sinh kết quả cuối cùng.

## **Chức năng 7: Quản trị bộ đệm ngắn hạn và Hợp nhất trí nhớ dài hạn**

| Thuộc tính | Đặc tả chi tiết luồng vận hành |
| :---- | :---- |
| **Bối cảnh vận hành** | Duy trì ngữ cảnh hội thoại giới hạn để tối ưu token; tự động thu thập, tóm tắt và lưu trữ tri thức định kỳ. |

*Luồng xử lý:* Sử dụng mảng lưu trữ 5 lượt tương tác hội thoại gần nhất (Sliding Window N=5) trên RAM. Đêm khuya, cronjob tự động quét nhật ký hội thoại trong ngày, loại bỏ các tác vụ thừa, tóm tắt nội dung nghiên cứu quan trọng và ghi vào `Profile.md` của kho lưu trữ Obsidian Vault (cơ chế Map-Reduce).

## **Chức năng 8: Kết xuất văn bản nghiên cứu khoa học (.docx)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành |
| :---- | :---- |
| **Bối cảnh vận hành** | Nhận yêu cầu xuất báo cáo và tạo tệp văn bản MS Word tại môi trường máy tính cục bộ. |

*Luồng xử lý:* Hệ thống RAG quét và trích xuất thông tin trọng tâm theo yêu cầu của người dùng, đưa dữ liệu vào LLM tạo lập cấu trúc báo cáo chi tiết. Thư viện `python-docx` sau đó định dạng, vẽ bảng, canh lề theo quy chuẩn văn bản học thuật và lưu tệp `*.docx` thành phẩm tại hệ thống tập tin cục bộ.

# **PHẦN 4: QUY TRÌNH QUẢN LÝ SOURCE CODE VÀ THƯ MỤC DỰ ÁN**

Cấu trúc cây thư mục tuân thủ kiến trúc phân rã thành các dịch vụ module nhỏ gọn (Micro-services logic):

```
digital-scholar/  
│
├── src/                         # Thư mục lõi chứa toàn bộ mã nguồn hệ thống
│   ├── core/                    # Logic điều phối và nhận diện ý định
│   │   ├── orchestrator.py      # Phân luồng tác vụ (RouterEngine, WorkerEngine)
│   │   ├── semantic_router.py   # Phân loại yêu cầu người dùng
│   │   └── regex_interceptor.py # Đánh chặn và thực thi các lệnh hệ thống (Zero-cost API)
│   │
│   ├── utils/                   # Các tiến trình hỗ trợ và bắt sự kiện nền
│   │   ├── watchdog_listener.py # Giám sát tài liệu mới được đưa vào hệ thống
│   │   └── parser.py            # Bóc tách tài liệu PDF/PPTX định dạng Markdown
│   │
│   ├── db/                      # Quản trị tương tác dữ liệu cơ sở
│   │   └── hybrid_rag.py        # Logic truy vấn kết hợp Qdrant và Neo4j Cloud
│   │
│   ├── services/                # Dịch vụ định kỳ và kết xuất văn bản
│   │   ├── docx_exporter.py     # Tạo lập báo cáo định dạng MS Word
│   │   └── memory_consolidator.py # Kịch bản tối ưu hóa bộ nhớ định kỳ (Map-Reduce)
│   │
│   └── ui/                      # Giao diện người dùng đồ họa (GUI)
│       ├── spotlight.py         # Cửa sổ nhận lệnh ẩn hiện tức thời
│       └── voice_engine.py      # Xử lý tương tác giọng nói và phiên dịch STT
│  
├── Obsidian_Vault/              # Không gian lưu trữ dữ liệu văn bản cục bộ (Local Markdown)
│   ├── 01_Inbox/                # Thư mục tiếp nhận tài liệu mới (PDF, PPTX)
│   ├── 02_Knowledge/            # Thư mục lưu trữ văn bản Markdown đã được xử lý
│   ├── 03_Agent_Memory/         # Bộ nhớ dài hạn vĩnh viễn (Profile.md)
│   └── 04_Schedules/            # Lịch biểu tự động khởi tạo
│  
├── qdrant_storage/              # Lưu trữ cơ sở dữ liệu vector cục bộ (Embedded)
├── assets/                      # Tài nguyên giao diện, tập tin cấu hình đa phương tiện
│
├── .env                         # Tệp cấu hình các tham số bảo mật và đường dẫn hệ thống
├── requirements.txt             # Định danh thư viện bắt buộc (qdrant-client, openai, google-genai...)
├── test_keys.py                 # Công cụ kiểm thử độc lập các luồng kết nối API lõi
├── run_tests.py                 # Bộ kiểm thử tự động nội bộ (Local Test Suite)
├── Huong_Dan_Su_Dung.md         # Hướng dẫn chi tiết cài đặt và khởi chạy hệ thống
└── main.py                      # Tệp khởi chạy tiến trình Daemon chính
```

# **PHẦN 5: QUẢN TRỊ RỦI RO (RISKS & TRADE-OFFS)**

Bảng quản trị ngoại lệ và khắc phục tự động phát sinh trong quá trình vận hành hệ thống:

| Rủi ro hệ thống | Mô tả sự cố tiềm ẩn | Hành động khắc phục tự động (Auto-Correction) |
| :---- | :---- | :---- |
| **1. Trì hoãn giao diện (UI Freezing)** | Quá trình bóc tách văn bản lớn hoặc độ trễ từ API có thể làm đóng băng luồng giao diện người dùng. | Áp dụng kỹ thuật đa luồng (QThread của PyQt kết hợp asyncio) để tách rời luồng đồ họa (Main UI Thread) và luồng xử lý nền (Worker Thread), đảm bảo giao diện luôn phản hồi mượt mà. |
| **2. Lặp lại truy vấn vô hạn (Infinite Loop)** | Nếu thông tin tìm kiếm nội bộ không đủ, hệ thống tự động tìm kiếm web. Quá trình tra cứu có thể lặp vô tận nếu ngữ cảnh mạng cũng không đáp ứng. | Thiết lập bộ giới hạn chu kỳ truy vấn (max_iterations = 3) trong LangGraph. Vượt số lần tối đa, hệ thống dừng tìm kiếm và phản hồi bằng lượng thông tin tốt nhất hiện có. |
| **3. Lỗi cấu trúc JSON đầu ra** | Các LLM thỉnh thoảng sinh ra định dạng JSON lỗi (chứa chuỗi thừa hoặc thiếu dấu ngoặc) gây dừng hoạt động khối phân tích. | Áp dụng 3 tầng kiểm thử: Chế độ Structured Output từ máy chủ LLM; biểu thức chính quy (Regex) làm sạch chuỗi; và khối try-except Pydantic Validation tự động yêu cầu LLM hiệu đính trong giới hạn 3 lần. |
| **4. Lỗi giới hạn tần suất (Rate Limit 429)** | Nạp dữ liệu đồng loạt khiến Google AI Studio từ chối yêu cầu truy xuất liên tục. | Chuyển luồng truy xuất tải trọng nặng (Auto-GraphRAG) thông qua cổng OpenRouter API để đảm bảo sự ổn định của lượng token, triệt tiêu mã lỗi Rate Limit. |

# **PHẦN 6: HƯỚNG DẪN CÀI ĐẶT VÀ TRIỂN KHAI (ONBOARDING)**

Tham khảo `Huong_Dan_Su_Dung.md` cho các tác vụ khởi chạy cơ bản. Dưới đây là các cấu hình kỹ thuật để khởi tạo môi trường phát triển:

## **6.1. Thiết lập tệp tin môi trường (.env)**

Khởi tạo tệp tin văn bản `.env` lưu tại thư mục gốc của dự án:

```
GEMINI_API_KEY="Khoa_api_gemini_chinh"  
OPENROUTER_API_KEY="Khoa_openrouter"  
NEO4J_URI="neo4j+ssc://xxx.databases.neo4j.io" 
NEO4J_USER="neo4j"  
NEO4J_PASSWORD="Mat_khau_database_cloud"  
OBSIDIAN_VAULT_PATH="C:/Users/Ten_Nguoi_Dung/Documents/Obsidian_Vault"
```

## **6.2. Triển khai môi trường và khởi chạy hệ thống**

Sử dụng Command Prompt hoặc PowerShell quyền Administrator thực hiện quy trình sau:

```bash
# 1: Chuyển đổi đường dẫn tới thư mục dự án
cd C:\Path\To\digital-scholar

# 2: Khởi tạo môi trường ảo Python (Virtual Environment)
python -m venv venv

# 3: Kích hoạt môi trường ảo
venv\Scripts\activate

# 4: Cập nhật trình quản lý thư viện pip
python -m pip install --upgrade pip

# 5: Cài đặt đồng loạt các gói thư viện phụ thuộc
pip install -r requirements.txt

# 6: Khởi chạy tệp định tuyến chính và đưa hệ thống vào nền
python main.py
```

Đồng ý cấp các quyền cơ bản (truy cập mạng, microphone) khi hệ điều hành hoặc phần mềm kiểm duyệt đưa ra yêu cầu trong lần chạy đầu tiên.

# **PHẦN 7: TỐI ƯU HÓA HỆ THỐNG VÀ XỬ LÝ ĐẶC THÙ**

## **7.1. Cấu hình đặc quyền hệ điều hành (OS Permissions)**

Hệ thống cần quyền truy cập cấp quản trị (Administrator) khi chạy `main.py` để sử dụng bộ thư viện điều hướng chuột/phím nền (keyboard hook). Việc chạy trong quyền hạn tiêu chuẩn có thể khiến phím tắt toàn cục bị vô hiệu hóa khi một phần mềm khác ở quyền ưu tiên hơn đang hiển thị.

## **7.2. Giải pháp đối phó bộ lọc nội dung đám mây (Safety Filters)**

Đối với các thuật ngữ y học, sinh học, hoặc bảo mật phức tạp, API Google đôi lúc dừng luồng yêu cầu (báo lỗi `FinishReason.SAFETY`). Hệ thống bọc khối phân tích bằng mệnh lệnh try-catch để ngăn ngừa lỗi ngắt luồng. Khi xảy ra sự cố kiểm duyệt, hệ thống phát thông báo cảnh báo qua đường truyền TTS nhằm báo cho người dùng thay vì treo ứng dụng nền.

## **7.3. Hợp nhất trí nhớ bằng thuật toán Map-Reduce định kỳ**

Modul `APScheduler` kích hoạt bộ dọn dẹp hàng đêm nhằm tối ưu không gian RAM. Hệ thống quét dữ liệu lịch sử hội thoại trong ngày lưu ở thư mục gốc (Map), phân tích bằng Gemini Flash để lọc bỏ các câu lệnh vận hành máy tính cơ bản, hợp nhất các lập luận khoa học trọng tâm (Reduce), sau đó ghi lại dài hạn vào tệp `03_Agent_Memory/Profile.md`.

# **PHẦN 8: ĐẶC TẢ API CONTRACT (DATA VALIDATION)**

Cấu trúc JSON phản hồi nghiêm ngặt từ các module, đảm bảo tính liên kết hợp lệ cho tầng Python logic:

## **8.1. API Contract của Mô hình Định tuyến ý định (Semantic Router)**

Đầu ra định tuyến xác định hướng giải quyết vấn đề của hệ thống RAG nội bộ:

```json
{  
  "intent_type": "research_query" | "os_control" | "daily_task" | "export_docx",   
  "target_folder": [  
    "/Obsidian_Vault/02_Knowledge/DeepLearning",  
    "/Obsidian_Vault/02_Knowledge/GraphRAG"  
  ], // Mảng đường dẫn thư mục liên quan, hoặc null nếu không phải tác vụ nghiên cứu 
  "enable_web_search": true, // Biến Boolean xác định quyền kích hoạt tìm kiếm Web tự động
  "os_action_payload": {  
    "app_name": "Zotero" | "Chrome" | "VS Code",  
    "action": "open"  
  } // Đối tượng thao tác phần mềm, hoặc null  
}
```

## **8.2. API Contract của Tác nhân Tự đánh giá (Self-Critique Schema)**

Cấu trúc điểm số nội dung được mô hình tự phân loại và kiểm định trước khi trả lời:

```json
{  
  "relevance_score": 9.2, // Hệ số tương quan nội dung (Thang 0.0 - 10.0)  
  "answerability_score": 8.5, // Độ tin cậy trả lời trọn vẹn câu truy vấn  
  "missing_information": "Nội dung phương pháp luận biểu đồ số 3 chưa có mặt tại thư viện lưu trữ nội bộ.", // Chuỗi cảnh báo tri thức khuyết thiếu  
  "action_required": "proceed" | "force_web_search" // Cờ trạng thái điều hướng LangGraph sang module mở rộng
}
```

--- Hết tài liệu Đặc tả Kiến trúc Digital Scholar (Agent V4.0) ---