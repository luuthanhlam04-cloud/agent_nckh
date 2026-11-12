# Hướng Dẫn Sử Dụng Hệ Thống Digital Scholar AI (Personal Research Cockpit V6.0)

Tài liệu này hướng dẫn chi tiết cách vận hành, trải nghiệm các tính năng cá nhân hàng ngày, tương tác giọng nói rảnh tay (Hands-free) và khai thác đối tác nghiên cứu học thuật (Research Cockpit).

---

## 1. KHỞI ĐỘNG HỆ THỐNG

| STT | Nơi thao tác | Hành động | Lệnh Terminal | Kết quả kỳ vọng |
| :---: | :--- | :--- | :--- | :--- |
| **1** | Terminal | Kích hoạt môi trường ảo | `.\venv\Scripts\activate` | Xuất hiện `(venv)` ở đầu dòng lệnh. |
| **2** | Terminal | Kiểm tra toàn diện hệ thống (Khuyên dùng) | `python production_check.py` | Quét AST 0 FAIL và vượt qua 51/51 Dynamic Tests. |
| **3** | Terminal | Khởi động hệ thống chạy ngầm | `python main.py` | Xuất hiện icon AI nhỏ ở khay hệ thống (System Tray) góc phải dưới màn hình. |

---

## 2. TRẢI NGHIỆM GIỌNG NÓI RẢNH TAY (HANDS-FREE VAD)

Hệ thống được trang bị mô hình mạng neural **Silero VAD (ONNX)** chạy trực tiếp trên CPU:

| Chế độ | Cách kích hoạt | Cách hoạt động thực tế |
| :--- | :--- | :--- |
| **VAD Tự Động (Hands-free - Mặc định)** | Đặt `VOICE_MODE=vad` trong file `.env` | 1. Bấm `Alt + Space` 1 lần.<br>2. Bạn nói tự nhiên, không cần giữ phím. Hệ thống có bộ đệm **500ms Pre-buffer** để không bao giờ bị nuốt phụ âm đầu câu ("Mở...", "Bật...").<br>3. Nói xong im lặng 1.5 giây, hệ thống tự động nhận diện và thực thi lệnh. |
| **Push-to-Talk (PTT)** | Đặt `VOICE_MODE=ptt` trong file `.env` | Giữ tổ hợp `Alt + Space` khi bắt đầu nói và nhả phím khi nói xong. |

---

## 3. ĐIỀU KHIỂN DESKTOP HÀNG NGÀY ($0 API, <1ms)

Nhờ bộ lọc **`HybridIntentSniffer` và Vietnamese Stopword Stripper**, bạn có thể nói chuyện bằng văn nói tiếng Việt đời thường, nhiều từ đệm rác mà hệ thống vẫn hiểu chính xác:

| Mục tiêu | Bạn có thể nói tự nhiên | Hệ thống tự lọc sạch và thực thi |
| :--- | :--- | :--- |
| **Mở YouTube** | *"Ờ... mở giùm tao cái... bài gì của Sơn Tùng ấy trên YouTube đi"* | Lọc sạch thành query `'Sơn Tùng'` $\rightarrow$ mở ngay trên YouTube |
| **Mở Trang chủ YouTube** | *"Ê mở YouTube coi"* | Mở thẳng trang chủ `youtube.com` |
| **Yêu cầu làm rõ** | *"Phát bài hát coi"* (chưa rõ tên) | Hệ thống hỏi lại: *"Bạn muốn mở bài hát hoặc video gì trên YouTube?"* |
| **Chỉnh Âm lượng** | *"Tắt tiếng giùm tao với"* / *"Chỉnh âm lượng 60%"* | Tắt tiếng hoặc đặt âm lượng chuẩn xác qua Windows API |
| **Khởi chạy App** | *"Bật giùm anh VS Code cái"* / *"Mở Chrome đi"* | Tự động bật ứng dụng tương ứng |
| **Xem Giờ / Ngày** | *"Bây giờ là mấy giờ rồi"* / *"Hôm nay thứ mấy"* | Trả lời tức thì ngày, giờ hệ thống |
| **Sao chép kết quả** | *"Copy câu vừa rồi"* | Lưu câu trả lời của AI vào Clipboard bộ nhớ tạm |

---

## 4. KHAI THÁC ĐỐI TÁC NGHIÊN CỨU HỌC THUẬT (RESEARCH COCKPIT)

Hệ thống đóng vai trò một **Socratic Thought Partner** hỗ trợ bạn tìm kiếm điểm nghẽn học thuật:

### 4.1. Nạp tài liệu tự động (Dual-Write)
- Bạn chỉ cần kéo thả file PDF hoặc PPTX bài báo khoa học vào thư mục:
  [Obsidian_Vault/01_Inbox/](file:///c:/Users/luuth/Desktop/agent_nckh/Obsidian_Vault/01_Inbox)
- Hệ thống tự động:
  1. Bóc tách văn bản theo cấu trúc đề mục C5 (`[Paper | Section | Page]`).
  2. Ghi vector chunks vào **Qdrant Local**.
  3. Dựng cây cấu trúc vật lý vào **Neo4j** (`(:Paper)-[:HAS_SECTION]->(:Section)-[:HAS_CHUNK]->(:Chunk)`).
  4. Lưu Markdown vào `02_Knowledge/` và di chuyển file gốc an toàn.

### 4.2. Hỏi đáp học thuật & Phản biện Socratic
- Mở thanh lệnh (`Ctrl + Space` hoặc `Alt + Space`), gõ câu hỏi nghiên cứu (ví dụ: *"Các giả định chính của GraphRAG khi mở rộng dữ liệu lớn"*).
- Sau khi trả lời dựa trên tài liệu đã nạp, Agent sẽ chủ động gợi ý phản biện:
  > *💡 Gợi ý phản biện học thuật (Socratic Thought Partner): Phương pháp trên có phụ thuộc vào giả định ngầm nào không? Nếu áp dụng vào bài toán thực tế của bạn, điểm nghẽn (bottleneck) lớn nhất nằm ở đâu?*

### 4.3. Quản lý nhật ký nghiên cứu (Research Journal)
- Toàn bộ các phát hiện về lỗ hổng, giả định ngầm hay điểm nghẽn sẽ được ghi chép vào:
  [Obsidian_Vault/05_Research_Journal/YYYY-MM-DD.md](file:///c:/Users/luuth/Desktop/agent_nckh/Obsidian_Vault/05_Research_Journal).
- Bạn có thể mở Obsidian lên vào mỗi buổi sáng để theo dõi nhật ký nghiên cứu liên tục của mình.

---

## 5. THOÁT VÀ DỌN DẸP HỆ THỐNG AN TOÀN

- **Cách 1 (Từ giao diện):** Click chuột phải vào Icon AI ở khay hệ thống (System Tray) $\rightarrow$ Chọn **Quit**.
- **Cách 2 (Từ Terminal):** Bấm tổ hợp `Ctrl + C` tại cửa sổ dòng lệnh đang chạy `main.py`.
- **Tự động Cleanup:** Hệ thống sẽ tự động giải phóng Hotkey toàn cục, đóng an toàn kết nối Qdrant/Neo4j và xả RAM sạch sẽ.
