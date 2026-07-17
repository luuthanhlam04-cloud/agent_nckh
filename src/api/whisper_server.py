"""
whisper_server.py - Local Microservice cho Whisper STT
======================================================
Chạy ngầm (Daemon) độc lập khỏi giao diện PyQt6.
Nhận file âm thanh qua POST /transcribe và trả về văn bản.
Cơ chế Auto-Port: tự dò tìm cổng trống từ 8001.
"""

import os
import sys
import json
import socket
import logging
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# Thiet lap log cho Server rieng
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [WhisperServer] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Tai model Whisper tu .env
from dotenv import load_dotenv
load_dotenv()
MODEL_NAME = os.getenv("WHISPER_MODEL", "vudang449/PhoWhisper-small-ct2")

# ==============================================================================
# WHISPER ENGINE (LOAD 1 LAN)
# ==============================================================================
_model = None


def init_model():
    global _model
    try:
        from faster_whisper import WhisperModel
        
        # [OPTIMIZATION] Khai thac kien truc CPU nang cao voi faster-whisper (CTranslate2)
        # CTranslate2 tu dong su dung tap lenh AVX2/AVX512 cua Intel Core Ultra
        optimal_threads = max(1, os.cpu_count() // 2)
        logger.info(f"Dang nap model '{MODEL_NAME}' tren CPU (INT8) voi {optimal_threads} luong...")
        logger.info(f"⚠️ NEU CHAY LAN DAU: He thong dang tai mo hinh AI (~800MB) chay ngam.")
        logger.info(f"⚠️ Vui long cho doi tu 5-30 phut tuy toc do mang va khong tat cua so nay!")
        
        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=optimal_threads)
        
        logger.info(f"Nap model faster-whisper hoan tat. RAM san sang.")
    except Exception as e:
        logger.error(f"Loi nap model faster-whisper: {e}", exc_info=True)
        sys.exit(1)

def transcribe_audio(wav_path: str) -> str:
    global _model
    if not _model:
        return ""
    try:
        # faster-whisper tra ve generator. Lay text tu segments
        segments, info = _model.transcribe(
            wav_path,
            language="vi",
            beam_size=1,
            condition_on_previous_text=False,
            temperature=0.0
        )
        text = " ".join([segment.text for segment in segments])
        return text.strip()
    except Exception as e:
        logger.error(f"Loi giai ma audio: {e}")
        return ""

# ==============================================================================
# HTTP SERVER HANDLER
# ==============================================================================
class WhisperRequestHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/ping":
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        elif parsed.path == "/shutdown":
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "shutting_down"}).encode("utf-8"))
            logger.info("Nhan duoc lenh shutdown tu UI. Dang tu sat...")
            # Phat tin hieu tat server tren luong khac de khong loi thread
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/transcribe":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                audio_data = self.rfile.read(content_length)
                
                if not audio_data:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": "No audio data"}).encode("utf-8"))
                    return

                # Luu ra file WAV tam thoi
                fd, path = tempfile.mkstemp(suffix=".wav")
                os.write(fd, audio_data)
                os.close(fd)

                # Giai ma
                text = transcribe_audio(path)
                
                # Don dep file WAV tam thoi
                try:
                    os.remove(path)
                except OSError:
                    pass  # File co the da bi xoa hoac bi khoa, bo qua
                
                self._set_headers(200)
                self.wfile.write(json.dumps({"text": text}).encode("utf-8"))
            except Exception as e:
                logger.error(f"Loi trong POST /transcribe: {e}")
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode("utf-8"))

    def log_message(self, format, *args):
        # Tat log request rác cua http.server (vi du ping)
        if args and "ping" in args[0]:
            return
        super().log_message(format, *args)


# ==============================================================================
# AUTO-PORT & MAIN LOOP
# ==============================================================================
def find_free_port(start_port=8001, max_port=8020):
    for port in range(start_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("Khong tim thay port ranh de chay Whisper Server.")

def main():
    try:
        # Tao thu muc temp neu chua co
        os.makedirs("temp", exist_ok=True)
        
        # 1. Nap Model truoc
        init_model()
        
        # 2. Tim cong ranh
        port = find_free_port()
        
        # 3. Ghi cong vao file de App chinh biet duong goi
        port_file = os.path.join("temp", ".whisper_port")
        with open(port_file, "w") as f:
            f.write(str(port))
            
        logger.info(f"Server Whisper STT da san sang tai http://127.0.0.1:{port}")
        
        # 4. Khoi chay Server
        server_address = ("127.0.0.1", port)
        httpd = HTTPServer(server_address, WhisperRequestHandler)
        httpd.serve_forever()
        
    except Exception as e:
        logger.error(f"Fatal Error: {e}", exc_info=True)
    finally:
        # Khi shutdown, xoa file port
        port_file = os.path.join("temp", ".whisper_port")
        if os.path.exists(port_file):
            try:
                os.remove(port_file)
            except OSError:
                pass  # File co the da bi xoa truoc do
        logger.info("Da thoat Whisper Server.")

if __name__ == "__main__":
    main()
