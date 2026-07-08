"""
voice_engine.py - Voice Mode STT (Giai doan 5)
=================================================
Xu ly ghi am va nhan dien giong noi (Speech-to-Text).
Dung pyaudio de thu am truc tiep, va Whisper-tiny (Local) de STT.

Kien truc Lazy Loading (Tiet kiem 200MB RAM):
  - Khong nap model vao RAM khi import hay khoi tao.
  - Chi load model vao RAM luc can giai ma (STT).
  - Giai ma xong -> del model -> gc.collect() de giai phong RAM ngay.
"""

import os
import wave
import tempfile
import logging
import gc
import threading
from typing import Optional

logger = logging.getLogger("VoiceEngine")

class VoiceRecorder:
    """Ghi am tu Microphone va luu vao file WAV tam thoi."""
    
    def __init__(self, chunk: int = 1024, format_type=None, channels: int = 1, rate: int = 16000):
        # Import pyaudio local de tranh loi neu chua cai
        try:
            import pyaudio
            self.pyaudio_instance = pyaudio.PyAudio()
            self.format_type = format_type or pyaudio.paInt16
        except ImportError:
            self.pyaudio_instance = None
            self.format_type = None
            
        self.chunk = chunk
        self.channels = channels
        self.rate = rate
        
        self.frames = []
        self._is_recording = False
        self._stream = None

    def start_recording(self):
        """Bat dau thu am non-blocking (chay ngam stream)."""
        if not self.pyaudio_instance:
            logger.error("[VoiceRecorder] Khong the thu am: Chua cai pyaudio.")
            return
            
        self.frames = []
        self._is_recording = True
        try:
            self._stream = self.pyaudio_instance.open(
                format=self.format_type,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )
            logger.info("[VoiceRecorder] Da mo microphone, dang thu am...")
            
            # Dung thread nho de doc du lieu lien tuc tranh mat frame
            self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
            self._record_thread.start()
        except Exception as e:
            logger.error("[VoiceRecorder] Loi mo microphone: %s", e)
            self._is_recording = False

    def _record_loop(self):
        """Doc audio frames lien tuc cho den khi _is_recording = False."""
        while self._is_recording and self._stream:
            try:
                data = self._stream.read(self.chunk, exception_on_overflow=False)
                self.frames.append(data)
            except OSError as e:
                # Loi the xay ra neu mic bi rut giua chung
                logger.error("[VoiceRecorder] Loi doc audio (Microphone ngat ket noi?): %s", e)
                self._is_recording = False
                break
            except Exception as e:
                logger.error("[VoiceRecorder] Loi khong xac dinh khi doc audio: %s", e)
                break

    def stop_recording(self) -> Optional[str]:
        """Dung thu am va luu vao file WAV. Tra ve duong dan file."""
        self._is_recording = False
        if hasattr(self, '_record_thread') and self._record_thread.is_alive():
            self._record_thread.join(timeout=1.0)
            
        if self._stream:
            try:
                # Kiem tra xem stream co bi stop dot ngot chua truoc khi call
                if not self._stream.is_stopped():
                    self._stream.stop_stream()
                self._stream.close()
            except OSError as e:
                logger.warning("[VoiceRecorder] Khong the dong stream do thiet bi da mat: %s", e)
            except Exception as e:
                logger.error("[VoiceRecorder] Loi dong stream: %s", e)
            finally:
                self._stream = None
            
        if not self.frames:
            logger.warning("[VoiceRecorder] Khong co du lieu audio.")
            return None

        # Ghi vao file temp
        try:
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            
            import pyaudio
            wf = wave.open(path, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.pyaudio_instance.get_sample_size(self.format_type))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(self.frames))
            wf.close()
            
            logger.info(f"[VoiceRecorder] Da luu audio ({len(self.frames)} frames) tai: {path}")
            return path
        except Exception as e:
            logger.error(f"[VoiceRecorder] Loi luu file WAV: {e}")
            return None

    def cleanup(self):
        """Dong pyaudio an toan."""
        if self.pyaudio_instance:
            try:
                self.pyaudio_instance.terminate()
            except Exception as e:
                logger.error("[VoiceRecorder] Loi terminate pyaudio: %s", e)
            finally:
                self.pyaudio_instance = None


class WhisperSTT:
    """Nhan dien giong noi (STT) su dung openai-whisper (tiny) voi Pre-Loading (Singleton)."""
    
    _instance = None
    _model = None

    def __new__(cls, model_name: str = "tiny"):
        if cls._instance is None:
            cls._instance = super(WhisperSTT, cls).__new__(cls)
            cls._instance.model_name = model_name
            cls._instance._load_model()
        return cls._instance

    def _load_model(self):
        """Nap model Whisper vao RAM (chi lam 1 lan)."""
        try:
            import whisper
            import torch
            
            logger.info(f"[WhisperSTT] Dang nap model '{self.model_name}' vao RAM (Pre-load)...")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.__class__._model = whisper.load_model(self.model_name, device=device)
            logger.info("[WhisperSTT] Da nap model Whisper thanh cong.")
        except ImportError as e:
            logger.error(f"[WhisperSTT] Chua cai thu vien whisper: {e}. Chay: pip install openai-whisper torch")
        except Exception as e:
            logger.error(f"[WhisperSTT] Loi nap model: {e}")

    def transcribe(self, audio_path: str) -> str:
        """
        Dich audio ra text. Model da duoc nap san nen cuc nhanh.
        """
        if not audio_path or not os.path.exists(audio_path):
            return ""
            
        text = ""
        try:
            import torch
            if self.__class__._model is None:
                return "Lỗi: Model Whisper chưa được nạp. Hãy kiểm tra logs."
                
            logger.info("[WhisperSTT] Dang giai ma audio...")
            # Nhan dien (force tieng Viet de nhanh & chuan hon)
            result = self.__class__._model.transcribe(audio_path, language="vi", fp16=torch.cuda.is_available())
            text = result.get("text", "").strip()
            logger.info(f"[WhisperSTT] Ket qua: '{text}'")
            
        except Exception as e:
            logger.error(f"[WhisperSTT] Loi giai ma: {e}")
            text = f"Lỗi giải mã giọng nói: {str(e)[:100]}"
        finally:
            # Xoa luon file audio tam
            try:
                os.remove(audio_path)
            except Exception:
                pass
                
        return text
