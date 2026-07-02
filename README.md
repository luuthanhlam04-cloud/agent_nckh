# **BẢN ĐẶC TẢ KIẾN TRÚC TOÀN DIỆN TỐI THƯỢNG: DIGITAL SCHOLAR (LAST AGENT V3.0)**

*Tài liệu Hợp nhất Kiến trúc Nền tảng, Quy trình Xử lý Đa tầng Thực chiến và Quản trị Rủi ro Production*

# **PHẦN 1: TỔNG QUAN HỆ THỐNG VÀ CHIẾN LƯỢC PHÁT TRIỂN**

Tài liệu Last Agent V3.0 xác lập toàn bộ thiết kế kiến trúc phần mềm, mô hình dữ liệu và các quy trình xử lý ngoại lệ thực chiến cho dự án **Digital Scholar**. Hệ thống vận hành dưới dạng một Local Background Daemon (Tiến trình chạy ngầm hệ điều hành) kết hợp các mô hình ngôn ngữ lớn (LLM) đám mây thương mại nhằm cung cấp một Trợ lý Ảo đa năng hỗ trợ Nghiên cứu Khoa học chuyên sâu và tự động hóa tác vụ.  
Hệ thống được thiết kế đặc thù nhằm giải quyết triệt để bài toán thắt cổ chai về phần cứng của người dùng (chỉ còn trống khoảng 5,7-7,7 RAM), đồng thời loại bỏ vĩnh viễn hiện tượng ảo giác học thuật (hallucination) và tối ưu hóa tối đa chi phí tài khoản token API thông qua cơ chế lai (Hybrid Architecture).

| Hạng mục đặc tả | Định hướng triển khai Production   |
| :---- | :---- |
| **Tên mã dự án** | Digital Scholar (Học giả Kỹ thuật số) \- Hybrid Research Agent |
| **Phiên bản / Giai đoạn** | Last Agent V3.0 \- Đóng gói kiến trúc tối thượng và hợp nhất mã nguồn Production Ready. |
| **Mục tiêu cốt lõi (Core Value)** | **1\. Nghiên cứu khoa học chuyên sâu (GraphRAG kép):** Tự động bóc tách tài liệu đa định dạng, kiến tạo sơ đồ tri thức logic qua đồ thị thực thể (Neo4j Cloud) kết hợp tìm kiếm tương đồng vector (Qdrant Local) nhằm giải phóng JVM và triệt tiêu hoàn toàn ảo giác thông tin. **2\. Trí nhớ phân tầng bảo mật:** Hệ thống quản trị trí nhớ dài hạn lưu tại Obsidian, trí nhớ ngắn hạn hoạt động bằng thuật toán cửa sổ trượt (Sliding Window N=5) giúp tiết kiệm token tối đa, trí nhớ ngầm định gom nhóm bằng Map-Reduce. **3\. Tiết kiệm token tuyệt đối (Zero-Cost):** Xây dựng lớp lá chắn Regex cục bộ đánh chặn 60% lệnh hệ thống và tác vụ sinh hoạt thường ngày mà không tốn chi phí gọi API. **4\. Tối ưu hóa tài nguyên phần cứng:** Hệ thống chạy ngầm tốn dưới 100MB RAM, giải mã giọng nói (STT Whisper-tiny) chạy trực tiếp trên nhân phần cứng NPU của máy tính cá nhân. |
| **Đối tượng sử dụng** | Nhà nghiên cứu khoa học độc lập, sinh viên đại học/sau đại học cần một "Bộ não thứ hai" bảo mật dữ liệu tuyệt đối nhưng vẫn muốn khai thác năng lực xử lý của các LLM cấp thương mại. |
| **Chiến lược phát triển** | \- Kiến trúc Não kép (Dual-Brain Routing): Dùng **Google Gemini Flash (Free Tier)** làm màng lọc định tuyến ý định siêu tốc; và ủy thác 100% tác vụ suy luận nặng (RAG, viết code, bóc PDF) cho cổng **OpenRouter (Pay-as-you-go)** để mở khóa băng thông vô cực, triệt tiêu lỗi Rate Limit.  **\- Ninja UX (Thanh lệnh biến mất):** Giao diện tối giản tàng hình, triệu hồi tức thời bằng phím tắt. Khi gửi dữ liệu, giao diện biến mất ngay lập tức, tự động xóa sạch thanh nhập liệu để lại thanh trống và phản hồi 100% bằng âm thanh qua tai nghe sếp. **\- Tự động sửa lỗi cấu trúc JSON:** Trấn áp tình trạng "lười biếng" hoặc trả kết quả sai định dạng của AI bằng cơ chế tự sửa lỗi tự động (Auto-Correction Loop) kết hợp Pydantic Validation thay vì chỉ phụ thuộc vào Prompt thông thường. |

# **PHẦN 2: KIẾN TRÚC HỆ THỐNG TỔNG THỂ (SYSTEM ARCHITECTURE)**

Hệ thống tuân thủ thiết kế module hóa phân rã nghiêm ngặt theo 5 tầng chức năng rõ ràng:

## **2.1. Tầng Giao diện & Trải nghiệm (UI/UX \- Frontend cục bộ)**

* **Nền tảng phát triển:** Ứng dụng native bằng thư viện PyQt6 hoặc PySide6 đạt tốc độ đồ họa tối đa trên Windows 11\.  
* **Cửa sổ lệnh Spotlight UI:** Thiết kế thanh nhập liệu tối giản, bo góc hiện đại tích hợp hiệu ứng làm mờ kính (Mica effect) của hệ điều hành.  
* **Luồng phân tách tương tác người dùng:**  
  * *Chế độ Text Mode:* Nháy đúp phím Enter nhanh \-\> Thanh Spotlight nổi lên, con trỏ chuột nhấp nháy sẵn sàng nhận văn bản gõ (phù hợp nơi đông người). Khi ấn Enter gửi đi, thanh Spotlight lập tức ẩn đi, xóa trắng bộ đệm nhập liệu.  
  * *Chế độ Voice Mode:* Nháy đúp phím Enter đồng thời nhấn giữ phím Space \-\> Kích hoạt Microphone, hiển thị sóng âm động (Audio Visualizer). Khi người dùng nhả phím Space, cửa sổ biến mất ngay lập tức và đóng gói âm thanh để xử lý ngầm.  
* **Phản hồi giọng nói (TTS Engine):** Sử dụng thư viện edge-tts kết nối máy chủ Azure thế nghe mới. Phản hồi âm thanh dạng luồng (Streaming Real-time), đọc loa ngay khi LLM nhả từ đầu tiên, tiêu tốn **0% RAM cục bộ**. Auto trả ra Voice 100% vào tai nghe người dùng.

## **2.2. Tầng Bộ não xử lý (Local Backend & OS Controller)**

* **Phương thức hoạt động:** Tiến trình Daemon chạy ngầm bằng Python 3.10+, chiếm dụng \< 100MB RAM khi ở chế độ chờ.  
* **Xử lý bất đồng bộ đa luồng:**  
  * asyncio: Quản lý hàng đợi tác vụ tập trung (Task Queue), đảm bảo không gây treo nghẽn khi vừa hội thoại vừa nạp tài liệu.  
  * watchdog: Giám sát liên tục thư mục 01\_Inbox/ của Obsidian Vault để tự động nạp dữ liệu ngầm ngay khi có file mới xuất hiện.  
  * APScheduler: Trình lên lịch cronjob cục bộ, kích hoạt luồng củng cố bộ nhớ dài hạn vào lúc 0:00 hàng đêm.  
* **Công cụ tương tác hệ điều hành (OS Tools):**  
  * Playwright (Python): Khởi chạy và điều khiển các trình duyệt Chrome/Edge ngầm để truy xuất HTML hoặc mở nhạc tự động.  
  * python-docx: Thay thế công năng cũ, chịu trách nhiệm tổng hợp tri thức học thuật từ hệ thống RAG và kết xuất tự động ra file Word báo cáo NCKH lưu Desktop sếp.  
  * Google Workspace API: Sử dụng giao thức xác thực OAuth 2.0 cục bộ để đọc dữ liệu lịch trình Google Calendar và nội dung hòm thư Gmail giáo sư.

## **2.3. Tầng AI & Logic chuyên sâu (Core Engine)**

* **Bộ định tuyến ý định (Semantic Router):** Sử dụng Gemini Flash API tốc độ cao để bóc tách cấu trúc ngôn ngữ của người dùng thành định dạng JSON ý định.  
* **Động cơ suy luận chính (Worker):** Sử dụng chuẩn kết nối của thư viện openai trỏ endpoint về OpenRouter API. Cấu hình linh hoạt gọi các mô hình thương mại (google/gemini-1.5-pro hoặc anthropic/claude-3.5-sonnet) để xử lý lượng token khổng lồ từ GraphRAG mà không bị nghẽn cổ chai.   
* **Đồ thị hóa tác vụ (LangGraph State Machine):** Xây dựng luồng tư duy ReAct đa bước. Hệ thống tự động chấm điểm ngữ liệu tìm được (Self-Critique). Nếu dữ liệu không đạt điểm chất lượng \> 8/10, LangGraph ép buộc Agent gọi DuckDuckGo API để bù đắp tri thức thiếu hụt từ Internet.  
* **Động cơ nhận diện giọng nói (STT Engine):** Mô hình Whisper-tiny giải mã giọng nói được biên dịch qua bộ thư viện OpenVINO, ép buộc chạy trực tiếp trên **lõi phần cứng NPU (Intel AI Boost)**, giải phóng 100% CPU.  
* **Bộ phân tách tài liệu học thuật (Parsing & Chunking):** Kết hợp Marker và PyMuPDF bóc PDF thành Markdown. Sử dụng Gemini Vision API đọc Slide PPTX dưới dạng ảnh, gài lệnh ngủ time.sleep(4) giữa mỗi slide để chống Rate Limit. Sử dụng chiến lược cắt phân đoạn theo ranh giới ngữ nghĩa của đoạn văn (Paragraph level).

## **2.4. Tầng Dữ liệu & Hạ tầng (Data & Storage)**

Bảng phân tích giải phóng tài nguyên bộ nhớ máy tính để giải quyết bài toán nút thắt cổ chai 5.7GB RAM trống:

| Thành phần dữ liệu | Giải pháp lưu trữ chốt hạ | Lý do kỹ thuật thực chiến (Trade-offs)   |
| :---- | :---- | :---- |
| **Long-term Memory** | **Obsidian Vault (Local Markdown)** | Toàn bộ dữ liệu gốc nằm an toàn vĩnh viễn trên ổ cứng máy tính của người dùng dưới dạng văn bản thuần, không đẩy file thô lên mạng, bảo mật tuyệt đối. |
| **Vector Database** | **Qdrant (Local Embedded Mode)** | Loại bỏ ChromaDB. Qdrant viết bằng lõi **Rust** quản lý RAM cực kỳ chặt chẽ, ghi thẳng file nhúng xuống ổ SSD NVMe cục bộ, triệt tiêu nguy cơ rò rỉ RAM (Memory Leak). |
| **Graph Database** | **Neo4j Cloud (Aura Free Tier)** | Đẩy đồ thị lên mây giúp giải phóng hoàn toàn gánh nặng của môi trường ảo Java (JVM) của bản Local Server vốn ngốn 1-2GB RAM liên tục. Sử dụng lược đồ tinh gọn để không chạm trần 200.000 nodes. |
| **Embedding Model** | **MiniLM-L12-v2 (Native Python Venv)** | Loại bỏ hoàn toàn Docker container vì nó bắt gánh thêm một OS Linux ảo và PyTorch nặng 3-5GB. Chạy native trên venv giúp mô hình nhúng chỉ chiếm \< 1GB RAM, băm văn bản đa ngôn ngữ miễn phí tốc độ cao. |

# **PHẦN 3: CHI TIẾT LUỒNG TÍNH NĂNG VÀ LOGIC XỬ LÝ ĐA TẦNG (PIPELINES)**

Hệ thống loại bỏ hoàn toàn các đoạn mô tả văn xuôi mơ hồ, cấu trúc chặt chẽ vòng đời của 8 tính năng lõi thông qua hệ thống bảng đặc tính kiến trúc và luồng xử lý tuần tự kết hợp mã nguồn thực thi cục bộ:

## **Chức năng 1: Nhận diện đa phương thức (Text/Voice Activation Ninja UX)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành   |
| :---- | :---- |
| **Bối cảnh vận hành** | Đánh chặn phím bấm toàn cục từ Windows, hiển thị Spotlight mờ Mica, phân tách Text/Voice. |
| **Trạng thái Dữ liệu** | Input: Sự kiện Keyboard / Audio Bytes từ Mic \-\> Output: Chuỗi văn bản sạch (String). |
| **Chỉ tiêu hiệu năng** | Thời gian giải mã Whisper trên NPU \< 200ms; thanh nhập liệu biến mất ngay lập tức (\< 16ms) khi gửi lệnh. |
| **Luồng âm thanh ra** | Mặc định auto trả ra Voice 100% vào tai nghe sếp qua edge-tts Streaming. Thanh nhập liệu biến mất để lại thanh trống hoàn toàn, loại bỏ giao diện lịch sử chat cồng kềnh. |

| Bước xử lý | Tiến trình hệ thống (Internal State) | Logic chuyển đổi dữ liệu   |
| ----- | :---- | :---- |
| **Step 1.1** | **Hotkey Interception** | Mã Python lắng nghe phím toàn cục qua thư viện keyboard. Nháy đúp Enter kích hoạt thanh Spotlight UI nổi lên trạng thái hoạt động. Con trỏ chuột focus vào TextBox. |
| **Step 1.2** | **Mode Bifurcation** | Nếu chỉ ấn phím gửi văn bản, TextBox thu thập chuỗi String. Nếu người dùng nháy đúp Enter và nhấn giữ phím Space, hệ thống chuyển sang trạng thái Voice Mode, kích hoạt pyaudio thu âm bytes thô vào bộ nhớ RAM tạm thời. |
| **Step 1.3** | **Ninja Visual Break** | Ngay khi người dùng nhả phím Space hoặc ấn phím gửi văn bản, hàm self.hide() được gọi lập tức. Cửa sổ biến mất khỏi màn hình, TextBox gọi lệnh clear() xóa trắng bộ đệm. Luồng dữ liệu chạy ngầm chuyển giao xuống cho tầng Core Engine xử lý. Sếp không nhìn thấy giao diện chat, chỉ chờ nghe Voice phản hồi vào tai nghe. |

## **Chức năng 2: Bộ giáp Regex đánh chặn cục bộ (Zero-Cost Interceptor)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành   |
| :---- | :---- |
| **Bối cảnh vận hành** | Đặt tại đầu cổng tệp lệnh main.py đánh chặn các lệnh thông thường nhằm đưa chi phí token về 0đ. |
| **Trạng thái Dữ liệu** | Input: Văn bản sạch \-\> Output: Thực thi mã Python trực tiếp / Hoặc nhả luồng đi tiếp xuống LLM. |
| **Triển khai đặc biệt** | Tích hợp 2 lệnh Regex độc quyền: **"Copy câu vừa rồi"** (đẩy text phản hồi cuối cùng vào Clipboard Windows để Ctrl+V dán ra Word) và **"Hiện chữ lên"** (gọi win11toast đẩy khung thông báo text nhỏ ở góc màn hình khi không nghe rõ). |

**Mã nguồn Production hoàn chỉnh của Bộ Giáp Regex 6 Module ghim cứng tại hệ thống:**

**1\. Bộ lọc câu nói rác từ khoảng lặng Whisper:**

import re

def filter\_whisper\_hallucination(audio\_text):  
    hallucination\_pattern \= r'^(Cảm ơn các bạn|Xin chào các bạn|Subtitles by|Amara\\.org|Cảm ơn quý vị|Thanks for watching|Chúc một ngày tốt lành).\*'  
    if re.search(hallucination\_pattern, audio\_text.strip(), re.IGNORECASE):  
        print("\[LÁ CHẮN\]: Đã hủy luồng chứa câu rác của Whisper do khoảng lặng âm thanh.")  
        return None  
    return audio\_text

**2\. Ghi nhớ ký ức nhanh vào Obsidian (Long-term Memory Update):**

def check\_and\_save\_to\_obsidian(user\_input):  
    memory\_pattern \= r'^(?:hãy|nhờ bạn|mày|quản gia|giúp tôi)?\\s\*(lưu|nhớ|ghi nhớ|lưu lại|lưu thông tin|note lại|thêm vào ghi chú|nhớ giúp tôi|ghi vào sổ|nhớ là)\\s\*(?:rằng|là|thông tin)?\\s+(.\*)'  
    match \= re.search(memory\_pattern, user\_input.strip(), re.IGNORECASE)  
    if match:  
        content\_to\_save \= match.group(2).strip()  
        vault\_file \= "C:/Users/Name/Documents/Obsidian\_Vault/03\_Agent\_Memory/Profile.md"  
        with open(vault\_file, "a", encoding="utf-8") as f:  
            f.write(f"\\n- \[{datetime.now().strftime('%d/%m/%Y %H:%M')}\]: {content\_to\_save}")  
        return f"Đã ghi nhớ trực tiếp vào Obsidian: {content\_to\_save}"  
    return None

**3\. Điều khiển HĐH và khởi chạy phần mềm hệ thống (OS Control):**

import os

def check\_os\_commands(user\_input):  
    os\_pattern \= r'^(?:hãy|quản gia)?\\s\*(mở|bật|khởi động|vào)\\s+(youtube|zalo|zotero|chrome|word|thư mục|vs code).\*'  
    match \= re.search(os\_pattern, user\_input.strip(), re.IGNORECASE)  
    if match:  
        app\_name \= match.group(2).strip().lower()  
        if app\_name \== "youtube":  
            os.system("start chrome https://youtube.com")  
            return "Đã mở Youtube cho sếp."  
        elif app\_name \== "zotero":  
            os.system("start zotero:")  
            return "Đã kích hoạt phần mềm trích dẫn Zotero."  
        elif app\_name \== "vs code":  
            os.system("code .")  
            return "Đã khởi chạy Visual Studio Code."  
    return None

**4\. Tra cứu thời gian và ngày tháng tĩnh:**

def check\_time\_queries(user\_input):  
    from datetime import datetime  
    if re.search(r'^(mấy giờ|bây giờ là mấy giờ|giờ hiện tại|quản gia mấy giờ rồi).\*', user\_input.strip(), re.IGNORECASE):  
        return f"Bây giờ là {datetime.now().strftime('%H:%M')} phút."  
    if re.search(r'^(hôm nay là ngày bao nhiêu|hôm nay ngày mấy|ngày hiện tại).\*', user\_input.strip(), re.IGNORECASE):  
        return f"Hôm nay là ngày {datetime.now().strftime('%d/%m/%Y')}."  
    return None

**5\. Lệnh ép buộc rẽ nhánh bỏ qua dữ liệu cũ để tra cứu Internet (Force Web Search):**

def force\_web\_search\_override(user\_input):  
    override\_pattern \= r'(tra mạng bắt buộc|bỏ qua dữ liệu cũ|tìm trên mạng|tìm trên google|search google|cập nhật mạng ngay)\\s\*(.\*)'  
    match \= re.search(override\_pattern, user\_input.strip(), re.IGNORECASE)  
    if match:  
        search\_query \= match.group(2).strip() if match.group(2).strip() else user\_input  
        return {"intent": "FORCE\_WEB", "query": search\_query}  
    return None

**6\. Lệnh trích xuất kết xuất báo cáo học thuật dạng Word (.docx):**

def trigger\_docx\_export(user\_input):  
    export\_pattern \= r'(xuất ra word|xuất báo cáo|lưu thành file word|tổng hợp thành file word|viết báo cáo word)\\s\*(.\*)'  
    match \= re.search(export\_pattern, user\_input.strip(), re.IGNORECASE)  
    if match:  
        return {"intent": "EXPORT\_DOCX", "topic": match.group(2).strip()}  
    return None

**7\. Lệnh tương tác sao chép text và gọi bảng phụ (Ninja UX Extensions):**

import pyperclip  
from win11toast import toast

def check\_ninja\_ux\_commands(user\_input, last\_voice\_response):  
    \# Lệnh copy văn bản phản hồi cuối cùng vào Clipboard Windows để sếp paste ra Word lập tức  
    if re.search(r'^(copy câu vừa rồi|sao chép câu trả lời|sao chép lại).\*', user\_input.strip(), re.IGNORECASE):  
        pyperclip.copy(last\_voice\_response)  
        return "Đã sao chép toàn bộ nội dung câu trả lời cuối cùng vào bộ nhớ tạm hệ thống."  
          
    \# Lệnh bật thông báo pop-up text khi không nghe rõ thuật ngữ học thuật phức tạp hoặc cách đánh vần  
    if re.search(r'^(hiện chữ lên|bật thông báo text|tao chưa nghe rõ|hiện text).\*', user\_input.strip(), re.IGNORECASE):  
        toast('Digital Scholar', last\_voice\_response, duration='short')  
        return "Đã hiển thị khung chữ văn bản bổ trợ ở góc màn hình Windows."  
          
    \# Lệnh bắt ép Agent đọc lại câu nói cũ mà không tốn token gọi lại API LLM đám mây  
    if re.search(r'^(nói lại xem|đọc lại câu vừa rồi|quản gia đọc lại).\*', user\_input.strip(), re.IGNORECASE):  
        return "REPEAT\_LAST\_VOICE" \# Rẽ luồng phát lại file audio bytes cũ trong bộ đệm RAM cục bộ  
    return None

## **Chức năng 3: Bộ định tuyến ý định dựa trên ngữ nghĩa đám mây (Semantic Router)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành   |
| :---- | :---- |
| **Bối cảnh vận hành** | Nhận diện ý định phức tạp của câu nói học thuật, phân vùng thư mục cần quét dữ liệu RAG nội bộ. |
| **Trạng thái Dữ liệu** | Input: Chuỗi câu hỏi sếp \+ Lịch xử bộ đệm cửa sổ trượt N=5 \-\> Output: JSON chuẩn cấu trúc định kiểu của Pydantic. |
| **Chỉ tiêu hiệu năng** | Thời gian xử lý định tuyến qua Gemini Flash API \< 500ms. Luôn trả về cấu trúc JSON hợp lệ nhờ JSON Mode máy chủ. |

| Bước xử lý | Tiến trình hệ thống (Internal State) | Logic chuyển đổi dữ liệu   |
| ----- | :---- | :---- |
| **Step 3.1** | **Contextual Stitching** | Mã Python lôi mảng biến chứa tối đa 5 cặp Hỏi-Đáp gần nhất từ RAM ghép nối vào câu lệnh mới của sếp làm dữ liệu mồi đầu vào. |
| **Step 3.2** | **JSON Mode Invocating** | Bắn gói tin lên Gemini Flash API, kích hoạt bộ cấu hình cưỡng bức response\_mime\_type. LLM đọc hiểu dòng lịch sử để nội suy ra thực thể ẩn (Ví dụ sếp hỏi câu 2: *"Bản báo cáo của nó nằm ở đâu"* \-\> Mô hình tự map chữ "Nó" thành "Thuật toán GraphRAG" được nói ở câu 1). |
| **Step 3.3** | **Routing Resolution** | Hệ thống nhả cục dữ liệu JSON chứa giá trị intent\_type và phân vùng mảng folder target\_folder. Hệ thống đọc dữ liệu rẽ nhánh sang tệp lệnh tương ứng của tầng Dữ liệu. |

## **Chức năng 4: Luồng trích xuất đồ thị tri thức tự động (Auto-GraphRAG Ingestion)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành   |
| :---- | :---- |
| **Bối cảnh vận hành** | Tự động quét ngầm thư mục, chuyển hóa tài liệu PDF học thuật thành cơ sở dữ liệu mối quan hệ logic và vector ngữ nghĩa. |
| **Trạng thái Dữ liệu** | Input: File cục bộ PDF, Slide PPTX thả vào Inbox \-\> Output: Đồ thị Nodes/Edges tại Neo4j Cloud \+ Vector tại Qdrant Local. |
| **Chốt chặn an toàn** | Cài lệnh ngủ cứng time.sleep(4) khi quét slide bằng Gemini Vision API nhằm tránh văng lỗi Rate Limit máy chủ Google (15 requests/phút). |

**Sơ đồ luồng xử lý tuần tự chi tiết khâu trích xuất (Auto-GraphRAG Pipeline):**

| Bước xử lý | Tiến trình hệ thống (Internal State) | Logic chuyển đổi dữ liệu   |
| ----- | :---- | :---- |
| **Step 4.1** | **Watchdog Triggering** | Tiến trình ngầm phát hiện tệp tin mới tại folder 01\_Inbox/. Gọi module parser.py ép file PDF/PPTX về dạng Markdown sạch sẽ lưu trữ sang folder 02\_Knowledge/. |
| **Step 4.2** | **Information Extraction** | Gửi tệp văn bản Markdown thô lên cổng OpenRouter (Gọi model Gemini Pro/Claude Sonnet)  kèm Prompt ép schema cấu trúcJSON chặt chẽ, bắt ép AI nhận diện bóc tách toàn bộ thực thể trọng tâm và liên kết logic biện chứng của bài báo khoa học. |
| **Step 4.3** | **Cypher Query Injection** | Mã Python bóc cục JSON cấu trúc vừa hứng được, tự động map giá trị lập tức sinh ra chuỗi các câu lệnh Cypher bản quyền để nạp thẳng lên máy chủ đám mây \*\*Neo4j Aura Cloud\*\* qua kết nối URI. |
| **Step 4.4** | **Local Vector Dual-Mapping** | Đồng thời, văn bản Markdown được băm thành các đoạn chunk nhỏ qua cơ chế Paragraph level, chạy nhúng qua mô hình MiniLM Local sinh vector lưu trữ tại Qdrant Local. Hệ thống lấy ID định danh duy nhất của chunk trong Qdrant gắn chặt vào trường Property thuộc tính dữ liệu của Node tương ứng trên Neo4j Cloud. Đồ thị và Vector chính thức đồng bộ chéo. |

## **Chức năng 5: Truy xuất lai kép kết hợp và Cơ chế RAG đa ngôn ngữ xuyên biên giới**

| Thuộc tính | Đặc tả chi tiết luồng vận hành   |
| :---- | :---- |
| **Bối cảnh vận hành** | Truy xuất tri thức học thuật sâu, giải quyết bài toán đặt câu hỏi bằng Tiếng Việt nhưng tài liệu lưu gốc viết bằng Tiếng Anh. |
| **Bản chất toán học** | Sử dụng mô hình nhúng MiniLM-multilingual, tự động đồng nhất tọa độ toán học nhiều chiều của các từ khóa ngữ nghĩa đồng cấp xuyên ngôn ngữ. Khoảng cách Cosine của câu hỏi Việt và text gốc Anh nằm sát khít nhau, tự mò ra data Anh chuyên ngành mà không tốn chi phí gọi API dịch thuật ngoài. |

| Bước xử lý | Tiến trình hệ thống (Internal State) | Logic chuyển đổi dữ liệu   |
| ----- | :---- | :---- |
| **Step 5.1** | **Prompt Keywords Translating** | Tại khâu Semantic Router, mã kích hoạt lệnh phụ dịch nhanh các từ khóa cốt lõi sang Tiếng Anh chuyên ngành phục vụ cho lệnh quét đồ thị Cypher. |
| **Step 5.2** | **Graph Structural Querying** | Mã Python quét mạng lưới quan hệ trên Neo4j Cloud, tìm thấy Nút thực thể logic học thuật dựa trên từ khóa tiếng Anh chuyên ngành ở bước trước. Rút được trường thuộc tính chứa ID chunk lưu trữ của Qdrant gài trên Nút. |
| **Step 5.3** | **Vector Dense Extraction** | Quay trở lại ổ cứng SSD máy local, lôi Qdrant Client ra truyền ID vào hàm rút dữ liệu. Hứng được chính xác toàn bộ đoạn văn bản xuôi Tiếng Anh chuyên ngành chi tiết của bài báo khoa học. Nhồi đống text gốc Anh này làm ngữ cảnh Context vào Prompt thô của cổng OpenRouter (Gọi model Gemini Pro/Claude Sonnet), bắt ép mô hình đọc phân tích ngữ cảnh tiếng Anh chuyên sâu nhưng bắt buộc kết xuất giọng thoại âm thanh phản hồi hoàn toàn bằng Tiếng Việt học thuật mượt mà vào tai nghe sếp. |

## **Chức năng 6: Đánh giá chất lượng dữ liệu nội bộ và Luồng ReAct (Critique Loop)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành   |
| :---- | :---- |
| **Bối cảnh vận hành** | Kiểm chuẩn tri thức local bốc được bằng mô hình AI chấm điểm (LLM-as-a-judge) đặt trong State Machine LangGraph. |
| **Trạng thái Dữ liệu** | Input: Context bốc từ RAG \-\> Output: Điểm số số thực JSON \-\> Quyết định đi tiếp trả lời hay nhảy nhánh ra Google/DuckDuckGo API tra mạng mở rộng. |

| Bước xử lý | Tiến trình hệ thống (Internal State) | Logic chuyển đổi dữ liệu   |
| ----- | :---- | :---- |
| **Step 6.1** | **Critique Evaluator** | Một modul AI siêu nhẹ quét đống context, đối chiếu câu hỏi gốc của sếp chấm điểm theo cấu trúc JSON Contract của Self-Critique Agent. Nhả về giá trị điểm số thực relevance\_score. |
| **Step 6.2** | **Conditional Branching** | Nếu điểm số đánh giá vượt mức trần \> 8/10, LangGraph kích hoạt trạng thái trả lời luôn. Nếu điểm dưới 8/10 (Kho local bị thiếu ngữ cảnh trầm trọng), hệ thống chặn luồng lại, chuyển trạng thái dữ liệu sang force\_web\_search, gọi DuckDuckGo API lướt cào Google tìm tri thức mới đắp vào context thô. |

## **Chức năng 7: Quản trị bộ đệm ngắn hạn và Hợp nhất trí nhớ dài hạn vĩnh viễn**

| Thuộc tính | Đặc tả chi tiết luồng vận hành   |
| :---- | :---- |
| **Bối cảnh vận hành** | Quản trị bộ đệm RAM hội thoại ngắn hạn bằng Cửa sổ trượt N=5; tự động kích hoạt cronjob dọn rác và tóm tắt tri thức vĩnh viễn lúc nửa đêm. |
| **Trạng thái Dữ liệu** | Input: Mảng chat log thô của ngày \-\> Output: File text chuẩn Markdown sạch sẽ ghi đè vào Profile.md trong Obsidian Vault. |

| Bước xử lý | Tiến trình hệ thống (Internal State) | Logic chuyển đổi dữ liệu   |
| ----- | :---- | :---- |
| **Step 7.1** | **Sliding Control** | Mã Python duy trì mảng Dictionary trên RAM chứa đúng lịch sử 5 cặp chat gần nhất. Khi xuất hiện câu chat thứ 6, câu thứ 1 tự động bị giải phóng (Pop/Delete) khỏi bộ nhớ RAM máy local, đóng trần token đầu vào gửi đi. |
| **Step 7.2** | **Map-Reduce Consolidation** | Đúng 0:00 đêm, APScheduler đánh thức script dọn rác. Tiến trình thực hiện cơ chế Map-Reduce: Quét sạch mảng log chat thô trong ngày (Map), nhồi lên Gemini Flash ra lệnh cạo sạch toàn bộ các câu lệnh thừa thãi (như lệnh mở app, bật nhạc, tra mạng google), cô đọng gom nhóm duy nhất các tri thức khoa học cốt lõi nảy sinh trong ngày (Reduce). Kết xuất chuỗi text sạch sẽ, chạy hàm văn bản ghi đè trực tiếp vĩnh viễn vào file cứng 03\_Agent\_Memory/Profile.md trong Obsidian Vault. |

## **Chức năng 8: Kết xuất đóng gói văn bản nghiên cứu khoa học chuyên nghiệp (.docx)**

| Thuộc tính | Đặc tả chi tiết luồng vận hành   |
| :---- | :---- |
| **Bối cảnh vận hành** | Nhận diện câu lệnh xuất báo cáo học thuật từ Bộ giáp Regex, đóng gói dữ liệu thành tệp văn bản Microsoft Word vật lý cứng lưu Desktop thay vì đọc loa phát thanh. |
| **Trạng thái Dữ liệu** | Input: Topic chủ đề nghiên cứu khoa học \-\> Output: File cứng định dạng .docx lưu tại màn hình Desktop máy sếp. |

| Bước xử lý | Tiến trình hệ thống (Internal State) | Logic chuyển đổi dữ liệu   |
| ----- | :---- | :---- |
| **Step 8.1** | **RAG Knowledge Gathering** | Hệ thống rẽ luồng chạy RAG quét toàn diện kho dữ liệu Qdrant và Neo4j Cloud, thu nạp tri thức, trích dẫn học thuật tương quan sâu sắc nhất đến Topic sếp yêu cầu. Đẩy dữ liệu thô lên cổng OpenRouter (Gọi model Gemini Pro/Claude Sonnet) bắt viết thành một cấu trúc văn bản luận văn học thuật hoàn chỉnh. |
| **Step 8.2** | **Docx Document Rendering** | Mã Python cục bộ đón chuỗi văn bản sạch, gọi thư viện python-docx khởi tạo một tệp tin Word mới. Tự động vẽ bảng ma trận so sánh, ghim đậm các tiêu đề đề mục lớn nhỏ, cấu hình giãn dòng học thuật và lưu tệp tin cứng định dạng \`.docx\` trực tiếp ra màn hình Desktop. Gọi loa thông báo: *"Đã kết xuất báo cáo khoa học ra màn hình Desktop thành công cho sếp."* |

# **PHẦN 4: QUY TRÌNH QUẢN LÝ SOURCE CODE VÀ THƯ MỤC DỰ ÁN**

Cấu trúc cây thư mục dự án tuân thủ kiến trúc phân rã module hóa Micro-services của bản V3.0 tối thượng, dọn sạch hoàn toàn các tệp tin của công nghệ cũ đã bị khai tử (Docker, ChromaDB, Code Review), lấy tệp lệnh main.py làm Entry Point điều hướng cổng nhiều lớp tuyệt đối:

digital-scholar/  
│  
├── agent\_core/                  \# Bộ não điều phối và lõi tư duy của Agent chuyên sâu  
│   ├── \_\_init\_\_.py  
│   ├── orchestrator.py          \#Chứa 2 Class phân luồng độc lập: RouterEngine (gọi Google SDK) và WorkerEngine (gọi OpenRouter/OpenAI SDK). Xóa bỏ logic Fallback rườm rà.   
│   ├── semantic\_router.py       \# Phân loại Intent RAG vs Web bằng Gemini Flash, cơ chế Prompt Keywords Translation  
│   └── regex\_interceptor.py     \# Module ghim cứng mã nguồn 7 hàm của Bộ Giáp Regex đánh chặn local (0 token)  
│  
├── data\_pipeline/               \# Đường ống bóc tách, tiêu hóa và lập chỉ mục văn bản học thuật chuyên sâu  
│   ├── \_\_init\_\_.py  
│   ├── watchdog\_listener.py     \# Tiến trình chạy ngầm phát hiện tệp tài liệu mới đổ vào folder Obsidian Inbox  
│   ├── parser.py                \# Bóc PDF bằng Marker/PyMuPDF; đọc Slide PPTX ngầm kèm hàm sleep trì hoãn 4 giây chống lỗi 429  
│   └── hybrid\_rag.py            \# Khởi chạy Qdrant cục bộ, kết nối Neo4j Cloud Driver, thực hiện ánh xạ đồng bộ ID chéo  
│  
├── ui/                          \# Tầng hiển thị đồ họa giao diện người dùng cục bộ Windows 11  
│   ├── \_\_init\_\_.py  
│   ├── spotlight.py             \# Cửa sổ thanh Spotlight nổi mờ Mica, bắt phím nóng Double Enter và giữ phím Space thoại  
│   └── voice\_engine.py          \# Đóng gói mô hình Whisper-tiny lên nhân phần cứng NPU và luồng audio bytes edge-tts Cloud  
│  
├── vault\_memory/                \# Khớp nối đường dẫn thư mục vật lý cứng trỏ thẳng tới kho lưu trữ Obsidian Vault  
│   ├── 01\_Inbox/                \# Trạm thu nạp: Nơi người dùng vứt file tài liệu PDF, PPTX thô vào để Agent tự ngửi dữ liệu  
│   ├── 02\_Knowledge/            \# Kho tri thức sạch: Chứa file văn bản Markdown thô đã được bóc tách và cấu trúc hóa hoàn toàn  
│   ├── 03\_Agent\_Memory/         \# Bộ nhớ dài hạn vĩnh viễn: Lưu trữ file Profile.md của thuật toán Map-Reduce đêm  
│   └── 04\_Schedules/            \# Lịch trình biểu: Folder chứa bảng biểu kế hoạch tuần tự động đẻ ra  
│  
├── .env                         \# Tệp tin text thuần lưu trữ các khóa bảo mật tối mật nội bộ (Bị chặn đẩy lên GitHub)  
├── requirements.txt             \# Khai báo các thư viện: qdrant-client,openai, google-generativeal, edge-tts, pydantic, openvino-telemetry...  
└── main.py                      \# Điểm kích hoạt Background Daemon duy nhất, chứa logic phân luồng rẽ nhánh đa lớp nghiêm ngặt

# **PHẦN 5: QUẢN TRỊ RỦI RO THỰC CHIẾN PRODUCTION (RISKS & TRADE-OFFS)**

Phần quản trị rủi ro sử dụng form ma trận bảng biểu kiểm chuẩn nghiêm ngặt của bản đặc tả cũ, tiến hành cô lập và gộp thêm các ngoại lệ API phát sinh của lõi kiến trúc V3 tối ưu:

| Rủi ro Production | Mô tả hiểm họa gãy hệ thống | Hành động khắc phục kỹ thuật tự động bằng mã Code (Auto-Correction)   |
| :---- | :---- | :---- |
| **1\. Treo đơ giao diện cửa sổ (UI Freezing)** | Khi Agent phải bóc tách file PDF học thuật nặng hàng trăm trang hoặc mải chờ tín hiệu API đám mây phản hồi lâu, luồng hiển thị của PyQt bị đơ đứng màn hình nhập liệu, Windows báo lỗi ứng dụng Not Responding. | Ứng dụng kỹ thuật đa luồng nâng cao. Sử dụng cơ chế QThread của PyQt kết hợp kiến trúc asyncio của Python để cô lập luồng. Tách biệt hoàn toàn Luồng hiển thị đồ họa (Main UI Thread) khỏi Luồng xử lý tính toán bóc tách và truy vấn cơ sở dữ liệu ngầm (Worker Thread). Thanh lệnh Spotlight luôn mượt mà. |
| **2\. Vòng lặp mạng vô tận (Infinite Loop)** | Khi Agent tự kiểm chuẩn thông tin RAG local bốc lên chấm điểm dưới mức trần 8/10, nó tự rẽ nhánh sang lướt mạng qua DuckDuckGo API, nếu cào mạng vẫn không đủ thông tin nó sẽ lặp lệnh cào mạng vô hạn gây cháy tài khoản và nghẽn băng thông mạng. | Cài đặt cầu dao an toàn cứng max\_iterations \= 3 trong lõi LangGraph State Machine. Quá 3 vòng tìm mạng mở rộng vẫn khuyết ngữ cảnh, ép hệ thống dừng tính toán lập tức, nhả luồng sinh văn bản dựa trên tri thức tốt nhất hiện có kèm dòng cảnh báo đỏ log lỗi hệ thống. |
| **3\. Lỗi Ảo giác cấu trúc JSON (Output JSON Lỏ)** | Kể cả khi cấu hình JSON Mode, Gemini thỉnh thoảng vẫn nhét thêm textblock Markdown bọc ngoài hoặc gãy dấu ngoặc đóng cú pháp khiến hàm json.loads() của Python chết đứng, gãy luồng xử lý câu lệnh. | Áp dụng chuỗi xử lý lỗi 3 lớp phòng vệ: 1\. Ép Structured Output ở API máy chủ Google. 2\. Dùng Regex re.search(r'\\{.\*\\}|\\\[.\*\\\]', response, re.DOTALL) để cắt phăng toàn bộ text rác bọc ngoài chuỗi cấu trúc dấu ngoặc nhọn. 3\. \*\*Auto-Correction Loop:\*\* Viết khối lệnh try-except bắt lỗi Validation của Pydantic, tự động ném đoạn thông báo lỗi cú pháp ngược lại cho Gemini Flash và bắt nó tự viết lại (Giới hạn tối đa 3 lần sửa sai). |
| **4\. Máy chủ đám mây từ chối (Rate Limit 429\)** | Khi người dùng ra lệnh dồn dập hoặc watchdog quét nạp quá nhiều file tài liệu khoa học cùng lúc lên hệ thống đám mây miễn phí, Google AI Studio sẽ sập kết nối hoặc báo lỗi quá tải chập chờn 503\. | Áp dụng kiến trúc Phân công tác vụ (Task-based Routing): Đẩy toàn bộ các luồng cắn nhiều token (Auto-GraphRAG Ingestion) đi thẳng qua cổng **OpenRouter**. Hệ thống dùng băng thông thương mại nên triệt tiêu hoàn toàn lỗi 429/503 của bản Google AI Studio . **Không cần viết code Fallback phức tạp gây nặng hệ thống.** . |

# **PHẦN 6: HƯỚNG DẪN CÀI ĐẶT VÀ TRIỂN KHAI CHI TIẾT (ONBOARDING)**

Bê nguyên bộ khung hướng dẫn cài đặt tường tận từng dòng dòng lệnh terminal của bản spec gốc nhằm phục vụ đắc lực cho khâu Onboarding, tiến hành thay ruột các thông số cấu hình công nghệ mới của bản V3:

## **6.1. Thiết lập tệp tin môi trường bảo mật cục bộ (.env)**

Khởi tạo file văn bản thuần đặt tên là .env lưu trữ trực tiếp tại thư mục gốc của dự án (Tuyệt đối không đẩy file này lên Git công khai):

GEMINI\_API\_KEY="AIzaSyA\_dien\_khoa\_api\_gemini\_studio\_chinh\_cua\_sep"  
OPENROUTER\_API\_KEY="sk-or-v1-dien\_khoa\_openrouter\_du\_phong\_fallback\_khi\_api\_google\_sap"  
NEO4J\_URI="neo4j+s://a1b2c3d4.databases.neo4j.io" \# Link đường dẫn URI lấy từ bảng điều khiển Neo4j Aura Cloud của sếp  
NEO4J\_USER="neo4j"  
NEO4J\_PASSWORD="Dien\_mat\_khau\_database\_cloud\_aura\_cap\_tai\_day"  
OBSIDIAN\_VAULT\_PATH="C:/Users/Ten\_May\_Sếp/Documents/Obsidian\_Vault" \# Đường dẫn tuyệt đối trỏ thẳng đến kho Obsidian Local trên ổ SSD

## **6.2. Chuỗi câu lệnh Terminal triển khai môi trường Production Ready**

Mở ứng dụng Command Prompt (cmd) hoặc PowerShell của Windows 11 dưới quyền quản trị tối cao \*\*Run as Administrator\*\* và gõ lệnh theo thứ tự cấu hình nghiêm ngặt sau:

\# Bước 1: Di chuyển sâu vào thư mục lưu trữ mã nguồn của dự án trên ổ cứng  
cd C:\\Path\\To\\Your\\Project\\digital-scholar

\# Bước 2: Khởi tạo môi trường ảo Python Virtual Environment nguyên bản để gạt bỏ hoàn toàn Docker nặng nề  
python \-m venv venv

\# Bước 3: Kích hoạt môi trường ảo vừa tạo để cô lập hoàn toàn các gói thư viện hệ thống  
venv\\Scripts\\activate

\# Bước 4: Nâng cấp trình quản lý gói pip của Python lên phiên bản mới nhất để chống lỗi phân tách bánh xe wheel  
python \-m pip install \--upgrade pip

\# Bước 5: Bơm đồng loạt toàn bộ các gói thư viện thực chiến tích hợp lõi nhúng Qdrant Rust và OpenVINO NPU  
pip install \-r requirements.txt

\# Bước 6: Kích hoạt chạy tệp lệnh điều phối chính để đưa hệ thống ẩn mình xuống khay Daemon hệ điều hành  
python main.py

Khi hệ điều hành Windows bật bảng hỏi bảo mật, tích chọn cấp toàn quyền truy cập mạng thiết bị, quyền sử dụng Microphone âm thanh và quyền chạy Subprocess điều khiển phần mềm cho Python. Nháy đúp Enter thử để bung Spotlight.

# **PHẦN 7: TỔNG HỢP TỐI ƯU HÓA VÀ CÁC KỸ THUẬT XỬ LÝ ĐẶC THÙ**

Tiêm vĩnh viễn đống "kinh nghiệm xương máu" thực chiến của file cũ vào bản V3 tối thượng nhằm xử lý các giới hạn vật lý nghẽn hệ thống của môi trường Windows:

## **7.1. Đặc quyền phân quyền Hệ điều hành mức sâu (OS Permissions)**

Việc chạy tệp main.py dưới quyền \*\*Administrator\*\* là bắt buộc tối cao. Nếu chạy quyền User thông thường, nhân Windows 11 sẽ tự động cô lập luồng và chặn đứng hàm bắt phím nền của thư viện keyboard, dẫn đến việc nháy đúp phím Enter hoàn toàn bị vô hiệu hóa nếu sếp đang mở hoặc làm việc trên một ứng dụng bên thứ ba khác đang chạy chiếm quyền ưu tiên.

## **7.2. Giải pháp bẫy lỗi Bộ lọc kiểm duyệt đám mây (Safety Filters Error Handling)**

Các mô hình Cloud của Google luôn bị áp đặt bộ lọc an toàn nghiêm ngặt và không hỗ trợ chế độ un-censored. Khi sếp nghiên cứu các tài liệu khoa học thuộc mảng Y học, Hóa học hoặc Tâm lý học thuật chuyên sâu, một số thuật ngữ chuyên ngành có thể kích hoạt nhầm bộ lọc này khiến API trả về mã lỗi ngắt kết nối đột ngột FinishReason.SAFETY. Để tránh việc ứng dụng bị crash gãy luồng, toàn bộ hàm gọi API trong orchestrator.py bắt buộc phải bọc trong khối lệnh try-catch ngoại lệ. Khi bắt được tín hiệu SAFETY, Agent tự động đánh chặn và xuất phản hồi giọng thoại thông minh vào tai nghe sếp: *"Tài liệu nghiên cứu chuyên ngành chứa thuật ngữ nhạy cảm bị bộ lọc an toàn của Google từ chối xử lý"*, giữ tiến trình ngầm ổn định vĩnh viễn.

## **7.3. Thuật toán Hợp nhất Trí nhớ định kỳ nửa đêm (Nocturnal Map-Reduce Memory)**

Tiến trình APScheduler cục bộ tự động chạy script dọn dẹp bộ đệm chat log vào đúng lúc 0:00 hàng đêm theo mô hình toán học Map-Reduce: Khâu Map quét sạch toàn bộ nhật ký cuộc chat thô nảy sinh trong ngày lưu ở thư mục tạm thời. Khâu Reduce đẩy mống data lôm côm đó lên mô hình Gemini Flash siêu nhẹ siêu rẻ cạo sạch các sự kiện rác thừa thãi (như lệnh mở app, bật nhạc), giữ lại duy nhất cốt lõi tri thức học thuật, củng cố trọng số logic cho các giả thuyết nghiên cứu khoa học được sếp nhắc đi nhắc lại nhiều lần, rồi ghi đè lưu trữ vĩnh viễn vào file text 03\_Agent\_Memory/Profile.md trong Obsidian Vault.

# **PHẦN 8: ĐẶC TẢ API CONTRACT CHUẨN HÓA (DATA VALIDATION)**

Bảo tồn cấu trúc khối code JSON mẫu kiểm chuẩn và định nghĩa biến cực kỳ nghiêm ngặt của bản spec gốc, cập nhật toàn bộ trường dữ liệu (Keys) bên trong để tương thích hoàn toàn với lõi logic tối ưu của V3:

## **8.1. API Contract của Mô hình Định tuyến ý định (Semantic Router Output Schema)**

Đầu ra cấu trúc từ Gemini Flash truyền xuống cho file điều hướng main.py xử lý rẽ nhánh Python cục bộ:

{  
  "intent\_type": "research\_query" | "os\_control" | "daily\_task" | "export\_docx",   
  "target\_folder": \[  
    "/Obsidian\_Vault/02\_Knowledge/DeepLearning",  
    "/Obsidian\_Vault/02\_Knowledge/GraphRAG"  
  \], // Mảng chứa các đường dẫn thư mục cần quét dữ liệu RAG local, trả về null nếu intent\_type là tác vụ khác  
  "enable\_web\_search": true, // Biến Boole cho phép hoặc cấm luồng ReAct lướt mạng mở rộng của LangGraph khi local khuyết dữ liệu  
  "os\_action\_payload": {  
    "app\_name": "Zotero" | "Chrome" | "VS Code",  
    "action": "open"  
  } // Đối tượng chứa tham số điều khiển phần mềm, trả về null nếu intent\_type là câu hỏi học thuật nghiên cứu đơn thuần  
}

## **8.2. API Contract của Mô hình Tự phản biện kiểm chuẩn dữ liệu (Self-Critique Agent Schema)**

Khối dữ liệu JSON chấm điểm chất lượng ngữ cảnh thu nạp được từ kho tri thức local trước khi cho phép Động cơ chính Orchestrator lập luận trả lời:

{  
  "relevance\_score": 9.2, // Điểm số đánh giá độ tương quan ngữ nghĩa của thông tin bốc được (Thang điểm số thực từ 0.0 đến 10.0)  
  "answerability\_score": 8.5, // Điểm số chấm mức độ tự tin để trả lời trọn vẹn câu hỏi gốc của người dùng  
  "missing\_information": "Luận điểm chứng minh tại biểu đồ số 3 của tài liệu bài báo khoa học chưa được nạp đầy đủ vào kho local", // Chuỗi thông báo mô tả phần tri thức bị khuyết thiếu  
  "action\_required": "proceed" | "force\_web\_search" // Nếu điểm tổng hợp dưới mức trần 8/10, tự động chuyển sang cờ force\_web\_search để ép LangGraph kích hoạt luồng tra cứu mạng DuckDuckGo mở rộng  
}

\--- Hết tài liệu Đặc tả Kiến trúc Toàn diện Last Agent V3.0 Tối Thượng \---