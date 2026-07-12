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
    """Ghi am tu Microphone va luu vao file WAV tam thoi."""

    def __init__(self, chunk: int = 1024, format_type=None, channels: int = 1, rate: int = 16000):
        try:
            import pyaudio
            self._pyaudio = pyaudio.PyAudio()
            self._format  = format_type or pyaudio.paInt16
        except ImportError:
            self._pyaudio = None
            self._format  = None

        self.chunk    = chunk
        self.channels = channels
        self.rate     = rate
        self._frames: list = []
        self._is_recording = False
        self._stream       = None
        self._record_thread: Optional[threading.Thread] = None

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
                format=self._format,
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
        """Doc audio frames lien tuc cho den khi _is_recording = False."""
        while self._is_recording and self._stream:
            try:
                data = self._stream.read(self.chunk, exception_on_overflow=False)
                self._frames.append(data)
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
                wf.setsampwidth(self._pyaudio.get_sample_size(self._format))
                wf.setframerate(self.rate)
                wf.writeframes(b"".join(self._frames))

            logger.info("[VoiceRecorder] Da luu %d frames -> %s", len(self._frames), path)
            return path
        except Exception as e:
            logger.error("[VoiceRecorder] Loi luu WAV: %s", e, exc_info=True)
            return None


class WhisperSTT:
    """
    Nhan dien giong noi (STT) su dung openai-whisper (tiny) voi Pre-Loading Singleton.

    Uu diem kien truc:
      - Singleton thread-safe (threading.Lock): khong load model 2 lan dung RAM.
      - fp16 flag duoc cache 1 lan o _load_model, khong goi syscall moi transcribe.
      - Tham so toc do cao: beam_size=1, condition_on_previous_text=False, temperature=0
        -> giam 40-60% latency so voi mac dinh.
    """

    _instance: Optional["WhisperSTT"] = None
    _model = None

    def __new__(cls, model_name: str = "tiny"):
        # [THREAD-SAFE FIX] Lock de tranh race condition khi 2 thread goi WhisperSTT()
        # dong thoi (preload thread va VoiceWorker) -> tranh load model 2 lan (~400MB lap)
        with _whisper_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst.model_name = model_name
                inst._use_fp16  = False  # Se duoc cap nhat trong _load_model
                inst._load_model()
                # [B1-FIX] Neu load that bai -> reset instance de lan sau thu lai
                if cls._model is None:
                    return None
                cls._instance = inst
        return cls._instance

    def _load_model(self):
        """Nap model Whisper vao RAM (chi lam 1 lan). Cache fp16 flag."""
        try:
            import whisper
            import torch

            # [FFMPEG-FIX] Inject ffmpeg vao PATH truoc khi nap model
            self._ensure_ffmpeg_in_path()

            # [OPT] Cache fp16 flag: tinh 1 lan, tranh torch.cuda syscall moi transcribe
            self._use_fp16 = torch.cuda.is_available()
            device = "cuda" if self._use_fp16 else "cpu"

            logger.info("[WhisperSTT] Dang nap model '%s' tren %s...", self.model_name, device.upper())
            t0 = time.perf_counter()
            self.__class__._model = whisper.load_model(self.model_name, device=device)
            elapsed = time.perf_counter() - t0
            logger.info("[WhisperSTT] Model nap xong trong %.1fs. RAM san sang.", elapsed)

        except ImportError as e:
            logger.error("[WhisperSTT] Thieu thu vien whisper/torch: %s. Chay: pip install openai-whisper torch", e, exc_info=True)
        except Exception as e:
            logger.error("[WhisperSTT] Loi nap model: %s", e, exc_info=True)

    @staticmethod
    def _ensure_ffmpeg_in_path():
        """
        Inject ffmpeg vao PATH neu chua co.
        Chi can thuc hien 1 lan, anh huong toan bo process.
        """
        import shutil
        if shutil.which("ffmpeg"):
            return  # Da co trong PATH

        candidates = []

        env_path = os.environ.get("FFMPEG_PATH", "")
        if env_path:
            candidates.append(env_path)

        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            winget_base = os.path.join(local_app, "Microsoft", "WinGet", "Packages")
            if os.path.isdir(winget_base):
                for entry in os.listdir(winget_base):
                    if "ffmpeg" in entry.lower():
                        pkg_dir = os.path.join(winget_base, entry)
                        for root, _, files in os.walk(pkg_dir):
                            if "ffmpeg.exe" in files:
                                candidates.append(root)
                                break

        for path in [
            os.path.join(os.path.expanduser("~"), "scoop", "shims"),
            r"C:\ProgramData\chocolatey\bin",
        ]:
            if os.path.isdir(path):
                candidates.append(path)

        for candidate in candidates:
            if os.path.isfile(os.path.join(candidate, "ffmpeg.exe")):
                os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
                logger.info("[WhisperSTT] Da inject ffmpeg vao PATH: %s", candidate)
                return

        logger.warning("[WhisperSTT] Khong tim thay ffmpeg. Whisper co the bi [WinError 2].")

    def transcribe(self, audio_path: str) -> str:
        """
        Giai ma audio -> text. Model da nap san nen nhanh.
        Tham so toc do cao: beam_size=1, temperature=0, no previous text.
        """
        if not audio_path or not os.path.exists(audio_path):
            return ""

        if self.__class__._model is None:
            return "Lỗi: Model Whisper chưa được nạp. Kiểm tra logs."

        text = ""
        try:
            logger.info("[WhisperSTT] Bat dau giai ma...")
            t0 = time.perf_counter()

            result = self.__class__._model.transcribe(
                audio_path,
                language="vi",
                fp16=self._use_fp16,        # [OPT] Dung cached flag thay vi goi syscall
                beam_size=1,                # [OPT] Giam tu 5 -> 1: nhanh hon ~40%
                best_of=1,                  # [OPT] Khong can multiple candidates
                condition_on_previous_text=False,  # [OPT] Khong dung previous context: nhanh hon
                temperature=0,             # [OPT] Greedy decode, deterministic, nhanh nhat
            )
            text = result.get("text", "").strip()
            elapsed = time.perf_counter() - t0
            logger.info("[WhisperSTT] Ket qua (%.1fs): '%s'", elapsed, text[:80])

        except Exception as e:
            logger.error("[WhisperSTT] Loi giai ma: %s", e, exc_info=True)
            text = f"Lỗi giải mã giọng nói: {str(e)[:100]}"
        finally:
            # Don audio file ngay sau khi doc
            try:
                os.remove(audio_path)
            except Exception:
                pass
            # [OPT] Giai phong tensor PyTorch o GPU/CPU sau inference
            gc.collect()

        return text
