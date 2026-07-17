"""
voice_engine.py - Voice Mode STT (Giai doan 5)
=================================================
Xu ly ghi am va nhan dien giong noi (Speech-to-Text).
Dung pyaudio de thu am truc tiep, va Whisper-tiny (Local) de STT.

Kien truc Pre-Loading Singleton (Tiet kiem RAM, Tang toc):
  - Load model 1 LAN duy nhat vao RAM khi khoi dong (Pre-Loading).
  - Thread-safe Singleton: threading.Lock bao ve khoi race condition.
  - Transcribe toc do cao: beam_size=1, condition_on_previous_text=False.
  - Cache fp16 flag: tinh 1 lan ket qua torch.cuda o __init__.
  - frames.clear() sau save WAV: giai phong RAM ghi am ngay.
"""

import os
import wave
import tempfile
import logging
import gc
import time
import threading
from typing import Optional

logger = logging.getLogger("VoiceEngine")

# ── Thread-safe lock cho Singleton WhisperSTT ─────────────────────────────────
_whisper_lock = threading.Lock()


class VoiceRecorder:
    """Ghi am tu microphone, luu file WAV, su dung VAD de tu dong ngat."""

    def __init__(self, on_silence_detected=None):
        import pyaudio
        self.chunk = 1024
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        self._pyaudio = pyaudio.PyAudio()
        self._stream = None
        self._frames = []
        self._is_recording = False
        self._record_thread = None
        self._on_silence_detected = on_silence_detected

    # ── Public API ────────────────────────────────────────────────────────────

    def start_recording(self):
        """Bat dau thu am non-blocking (stream chay ngam trong thread)."""
        if not self._pyaudio:
            logger.error("[VoiceRecorder] Khong the thu am: Chua cai pyaudio.")
            return

        self._frames = []
        self._is_recording = True
        try:
            self._stream = self._pyaudio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk,
            )
            logger.info("[VoiceRecorder] Da mo microphone, dang thu am...")
            self._record_thread = threading.Thread(
                target=self._record_loop, daemon=True, name="AudioRecorder"
            )
            self._record_thread.start()
        except Exception as e:
            logger.error("[VoiceRecorder] Loi mo microphone: %s", e, exc_info=True)
            self._is_recording = False

    def stop_recording(self) -> Optional[str]:
        """Dung thu am va luu vao file WAV. Tra ve duong dan file."""
        self._is_recording = False

        if self._record_thread is not None and self._record_thread.is_alive():
            self._record_thread.join(timeout=1.0)
        self._record_thread = None

        if self._stream:
            try:
                if not self._stream.is_stopped():
                    self._stream.stop_stream()
                self._stream.close()
            except OSError as e:
                logger.warning("[VoiceRecorder] Stream da mat ket noi: %s", e, exc_info=True)
            except Exception as e:
                logger.error("[VoiceRecorder] Loi dong stream: %s", e, exc_info=True)
            finally:
                self._stream = None

        if not self._frames:
            logger.warning("[VoiceRecorder] Khong co du lieu audio.")
            return None

        path = self._save_wav()
        # [OPT] Giai phong RAM ghi am ngay sau khi save
        self._frames.clear()
        return path

    def cleanup(self):
        """Dong pyaudio an toan khi app thoat."""
        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception as e:
                logger.error("[VoiceRecorder] Loi terminate pyaudio: %s", e, exc_info=True)
            finally:
                self._pyaudio = None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _record_loop(self):
        """Doc audio frames lien tuc cho den khi _is_recording = False hoac VAD tu ngat."""
        import audioop
        CALIBRATION_DURATION = 0.5 # 0.5 giay dau de do on nen (Auto-Calibration)
        SILENCE_DURATION = 1.2     # [FIX] VAD ve muc an toan 1.2s cho dac thu am vuc Tieng Viet (Giữ Ultra-Low Latency)
        
        frames_per_sec = self.rate / self.chunk
        max_silence_frames = int(SILENCE_DURATION * frames_per_sec)
        calibration_frames_count = int(CALIBRATION_DURATION * frames_per_sec)
        
        silence_count = 0
        speech_count = 0           # Đếm số frame liên tiếp vượt ngưỡng để lọc tiếng gõ phím
        min_speech_frames = int(0.2 * frames_per_sec) # ~3 frames (0.2s)
        has_spoken = False
        
        is_calibrating = True
        calibration_rms_list = []
        silence_threshold = 500  # Default fallback

        while self._is_recording and self._stream:
            try:
                data = self._stream.read(self.chunk, exception_on_overflow=False)
                self._frames.append(data)
                
                # VAD: Tinh nang luong am thanh
                rms = audioop.rms(data, 2)
                
                if is_calibrating:
                    calibration_rms_list.append(rms)
                    if len(calibration_rms_list) >= calibration_frames_count:
                        is_calibrating = False
                        avg_noise = sum(calibration_rms_list) / len(calibration_rms_list)
                        # Threshold = Noise + 400 (buffer tranh tieng tho, on nen), min la 800
                        silence_threshold = max(800, int(avg_noise + 400))
                        logger.info("[VoiceRecorder] Calibration xong. Noise: %.1f, Threshold: %d", avg_noise, silence_threshold)
                    continue  # Bo qua VAD check trong luc dang calibrate
                
                if rms > silence_threshold:
                    silence_count = 0
                    speech_count += 1
                    if speech_count >= min_speech_frames:
                        has_spoken = True
                else:
                    speech_count = 0
                    if has_spoken:
                        silence_count += 1
                        
                # Tu dong ngat khi im lang du lau (chi khi da tung noi)
                if has_spoken and silence_count > max_silence_frames:
                    logger.info("[VoiceRecorder] Phat hien im lang > 1.5s. Tu dong ngat mic.")
                    self._is_recording = False
                    if self._on_silence_detected:
                        self._on_silence_detected()
                    break
                    
            except OSError as e:
                logger.error("[VoiceRecorder] Microphone ngat ket noi: %s", e, exc_info=True)
                self._is_recording = False
                break
            except Exception as e:
                logger.error("[VoiceRecorder] Loi doc audio: %s", e, exc_info=True)
                break

    def _save_wav(self) -> Optional[str]:
        """Ghi frames vao file WAV tam thoi, tra ve duong dan."""
        try:
            # [FIX] Tao file tam va dong fd TRUOC khi wave.open de tranh PermissionError Win
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)

            with wave.open(path, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self._pyaudio.get_sample_size(self.format))
                wf.setframerate(self.rate)
                wf.writeframes(b"".join(self._frames))

            logger.info("[VoiceRecorder] Da luu %d frames -> %s", len(self._frames), path)
            return path
        except Exception as e:
            logger.error("[VoiceRecorder] Loi luu WAV: %s", e, exc_info=True)
            return None


class WhisperSTT:
    """
    Nhan dien giong noi (STT) su dung Local Microservice (whisper_server.py).
    
    Uu diem kien truc (Moi):
      - Khong load torch/whisper trong tien trinh nay, ne GIL, bao ve RAM UI.
      - Doc cong (port) tu temp/.whisper_port de tu dong cap nhat port moi.
      - Gui request POST den server de giai ma giong noi.
    """

    _instance: Optional["WhisperSTT"] = None

    def __new__(cls, model_name: str = "small"):
        with _whisper_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst.model_name = model_name
                cls._instance = inst
        return cls._instance

    def _get_server_port(self) -> int:
        port_file = os.path.join("temp", ".whisper_port")
        if os.path.exists(port_file):
            try:
                with open(port_file, "r") as f:
                    return int(f.read().strip())
            except (OSError, ValueError) as e:
                logger.warning("[WhisperSTT] Khong doc duoc port file: %s", e)
        return 8001  # Fallback neu chua co file

    def _ping_server(self, port: int) -> bool:
        import urllib.request
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/ping", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as response:
                return response.status == 200
        except Exception:
            # Ping that bai la binh thuong khi server chua khoi dong
            return False

    def _load_model(self):
        """Khong con load model vao RAM o day nua. Chi ping de chac chan server song."""
        port = self._get_server_port()
        if self._ping_server(port):
            logger.info(f"[WhisperSTT Client] Da ket noi thanh cong Whisper Server tai port {port}")
        else:
            logger.warning(f"[WhisperSTT Client] Chua the ping den Whisper Server o port {port}. Server co the chua khoi dong xong.")

    def transcribe(self, audio_path: str) -> str:
        """Gui file WAV den Whisper Server de giai ma. Tra ve van ban."""
        port = self._get_server_port()
        import time
        import urllib.request
        import json

        start_t = time.time()
        logger.info(f"[WhisperSTT Client] Bat dau gui audio toi server port {port}...")
        try:
            with open(audio_path, "rb") as f:
                audio_data = f.read()

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/transcribe", 
                data=audio_data, 
                headers={'Content-Type': 'application/octet-stream'},
                method="POST"
            )
            
            # [BLOCKING FIX] Nham bao ve UI, tham so timeout dc tang len 30s de ho tro CPU yeu load model nang
            with urllib.request.urlopen(req, timeout=30.0) as response:
                result_json = response.read().decode('utf-8')
                result = json.loads(result_json)
                text = result.get("text", "")

            logger.info(f"[WhisperSTT Client] Ket qua (%.1fs): '%s'", time.time() - start_t, text)
            return text
        except urllib.error.URLError as e:
            logger.error("[WhisperSTT Client] Khong the ket noi toi server: %s", e, exc_info=True)
            return f"Lỗi: Không thể kết nối máy chủ nhận diện giọng nói (Port {port})."
        except Exception as e:
            logger.error("[WhisperSTT Client] Loi giai ma: %s", e, exc_info=True)
            return f"Lỗi giải mã giọng nói: {str(e)[:100]}"
        finally:
            # Don audio file ngay sau khi doc
            try:
                os.remove(audio_path)
            except Exception as e:
                logger.debug("[VoiceWorker] Khong the xoa file audio_path cu: %s", e)
            import gc
            gc.collect()
