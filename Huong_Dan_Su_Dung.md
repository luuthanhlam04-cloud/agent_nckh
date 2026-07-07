# Hướng Dẫn Sử Dụng Hệ Thống Digital Scholar AI

Tài liệu này hướng dẫn cách khởi chạy, kiểm thử các tính năng giao diện (kể cả khi chưa thiết lập API Key) và cách đóng hệ thống an toàn.

---

## 1. KHỞI ĐỘNG HỆ THỐNG

| STT | Cửa sổ / Nơi thao tác | Hành động bạn cần làm | Lệnh gõ (Terminal) | Kết quả kỳ vọng |
| :---: | :--- | :--- | :--- | :--- |
| **1** | Terminal (VSCode) | Bật môi trường ảo | `venv\Scripts\activate` | Hiện chữ `(venv)` ở đầu dòng lệnh. |
| **2** | Terminal (VSCode) | Chạy dự án ở chế độ ngầm | `python main.py` | Hiện log khởi tạo. Xuất hiện icon AI nhỏ ở khay hệ thống (System Tray) góc phải dưới màn hình. |

---

## 2. TEST TÍNH NĂNG GIAO DIỆN & LÕI LOCAL
> **Lưu ý:** Phần này hướng dẫn test độ mượt của UI, Phím tắt, và Lõi AI Cục bộ (Local AI) ngay cả khi **chưa cấu hình API Key** (Gemini/Neo4j).

| STT | Chế độ | Bấm phím / Mệnh lệnh | Kết quả kỳ vọng (Test Offline) |
| :---: | :--- | :--- | :--- |
| **1** | Mở Thanh Lệnh | Bấm `Ctrl + Space` ở bất kỳ đâu. | Thanh lệnh văng ra giữa màn hình. AI đọc câu chào "Xin chào..." |
| **2** | Test "Chen Ngang" | Đang nghe câu chào, bạn gõ liền phím `a` | AI lập tức dừng nói (Ngắt âm thanh hoàn hảo). |
| **3** | Test Lõi LLM (No API) | Gõ thử *"Chào bạn"* -> Bấm `Enter` | Hệ thống báo lỗi "Core AI chưa sẵn sàng. Kiểm tra API Keys...". App **không bị crash hay văng!** |
| **4** | Thu Gọn UI | Bấm `ESC` khi đang mở bảng | Giao diện thu gọn và chạy ngầm dưới hệ thống. |
| **5** | Test Lõi Giọng Nói Local | Bấm `Ctrl + Shift + Space` | Nghe lời chào -> Im lặng khóa mic -> Lời chào xong -> Mở mic (Có chữ "Đang nghe"). |
| **6** | Nói thử (Whisper) | Đọc to: *"Hôm nay thứ mấy"* vào Micro | Đợi 2-3s (Whisper chạy nội bộ bằng CPU). Thanh lệnh sẽ tự động hiện ra dòng chữ bạn vừa đọc. *(Do chưa cấu hình API nên sau khi dịch ra chữ, đoạn hội thoại sẽ dừng lại)*. |

---

## 3. THOÁT VÀ ĐÓNG DỰ ÁN AN TOÀN

Hệ thống được thiết kế chạy ngầm (Daemon). Vì vậy, bạn cần biết cách đóng an toàn để hệ thống xả RAM và trả lại Phím tắt (Hotkeys) cho Windows.

| STT | Tình huống | Cách đóng / Thoát | Lệnh gõ (Terminal) |
| :---: | :--- | :--- | :--- |
| **1** | Đóng từ Giao diện | Dưới khay hệ thống (Góc phải màn hình, cạnh đồng hồ), bấm chuột phải vào Icon dự án -> Chọn **Quit** (Thoát) | Không cần gõ lệnh |
| **2** | Đóng từ Terminal | Quay lại Terminal đang chạy lệnh `python main.py`, bấm tổ hợp phím `Ctrl + C` | Không cần gõ lệnh |
| **3** | Thoát môi trường ảo | Sau khi app đã tắt, dọn sạch Terminal | `deactivate` |

> 💡 **Lưu ý:** Khi bấm Quit hoặc `Ctrl+C`, trên Terminal sẽ có các log ghi nhận: *"Đang dọn dẹp Hotkey", "Đang ngắt Qdrant", "Đang xả RAM..."*. Đó chính là quy trình **Cleanup Component** giúp dọn dẹp tài nguyên và bảo vệ phần cứng máy tính!

---
*Chúc bạn trải nghiệm hệ thống thật mượt mà! 😎*
