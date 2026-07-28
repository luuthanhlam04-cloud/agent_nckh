"""
voice_engine.py - Voice Mode STT (Refactored: Whisper -> Gemini Cloud API)
===========================================================================
Kien truc moi (don gian hon nhieu):

  VoiceRecorder : pyaudio ghi am, simple RMS VAD phat hien am thanh.
                  stop_recording() tra ve raw PCM bytes (khong luu file).

  GeminiSTT     : Thread-safe Singleton. Nhan PCM bytes -> wrap WAV header
                  trong bo nho -> gui Gemini API -> tra ve van ban.
                  Khong subprocess, khong HTTP IPC, khong file tam tren disk.

So sanh voi phien ban cu:
  Da xoa: WhisperSTT (singleton HTTP client, port file reader, 8-layer IPC)
  Da xoa: _whisper_lock (threading.Lock cho Whisper)
  Da xoa: webrtcvad dependency
  Giu lai: VoiceRecorder (pyaudio + logic ghi am co ban)
  Thay doi: stop_recording() tra bytes thay vi Optional[str] (file path)
  Them moi: GeminiSTT class (Gemini Cloud API inline audio)

Tuan thu ARCHITECTURE_RULES.md:
  - gc.collect() bat buoc trong transcribe() (production_check.py Rule)
  - Thread-safe Singleton bang threading.Lock
  - logging day du, khong dung print()
  - Khong goi blocking API tren Main Thread (chi goi tu VoiceWorker QThread)
"""

import gc
import io
import logging
import os
import threading
import time
import wave
from typing import Optional

logger = logging.getLogger("VoiceEngine")

# ── Hang so cau hinh ──────────────────────────────────────────────────────────
AUDIO_CHUNK_FRAMES    = 480    # 30ms tai 16000Hz (16000 * 0.03 = 480 frames)
AUDIO_FORMAT_WIDTH    = 2      # int16 = 2 bytes/sample
AUDIO_CHANNELS        = 1      # mono
AUDIO_SAMPLE_RATE     = 16000  # Hz
SILENCE_DURATION_SEC  = 1.5    # Giay im lang de tu dong ngat mic (VAD mode)
MIN_AUDIO_DURATION    = 1.5    # Giay toi thieu, ngay hon se bi bo qua
RECORD_TIMEOUT_SEC    = 30     # Giay toi da ghi am (bao hiem)
RMS_SPEECH_THRESHOLD  = 300    # Nguong RMS phan biet tieng noi vs tieng on
GEMINI_STT_MODEL      = "gemini-3.1-flash-lite"

# ── Singleton lock cho GeminiSTT ──────────────────────────────────────────────
_gemini_stt_lock = threading.Lock()


# ==============================================================================
#  VoiceRecorder — Thu am tu microphone
# ==============================================================================

class VoiceRecorder:
    """
    Ghi am tu microphone, su dung RMS don gian de phat hien giong noi.

    Thay doi so voi phien ban cu:
      - stop_recording() tra ve Optional[bytes] thay vi Optional[str] (file path)
      - Loai bo webrtcvad dependency (khong con can phan loai audio offline)
      - Giu lai logic VAD don gian bang audioop.rms (built-in Python)
    """

    def __init__(self, on_silence_detected: Optional[callable] = None):
        import pyaudio
        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._frames: list[bytes] = []
        self._is_recording: bool = False
        self._record_thread: Optional[threading.Thread] = None
        self._on_silence_detected = on_silence_detected
        logger.info("[VoiceRecorder] Khoi tao xong (pyaudio, %dHz, mono).", AUDIO_SAMPLE_RATE)

    # ── Public API ────────────────────────────────────────────────────────────

    def start_recording(self) -> None:
        """Bat dau thu am non-blocking trong daemon thread."""
        self._frames = []
        self._is_recording = True
        try:
            import pyaudio
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=AUDIO_CHANNELS,
                rate=AUDIO_SAMPLE_RATE,
                input=True,
                frames_per_buffer=AUDIO_CHUNK_FRAMES,
            )
            self._record_thread = threading.Thread(
                target=self._record_loop, daemon=True, name="AudioRecorder"
            )
            self._record_thread.start()
            logger.info("[VoiceRecorder] Micro da mo, dang thu am...")
        except Exception as e:
            logger.error("[VoiceRecorder] Loi mo microphone: %s", e, exc_info=True)
            self._is_recording = False

    def stop_recording(self) -> Optional[bytes]:
        """
        Dung thu am, tra ve raw PCM16 bytes.

        Tra ve None neu:
          - Khong co du lieu audio
          - Audio qua ngan (< MIN_AUDIO_DURATION giay)

        Luu y: Khac phien ban cu (tra file path). Nay tra bytes truc tiep
        de GeminiSTT xu ly ma khong can luu file tam tren disk.
        """
        self._is_recording = False

        if self._record_thread and self._record_thread.is_alive():
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

        # Guard: kiem tra do dai audio toi thieu
        min_frames = int(MIN_AUDIO_DURATION * (AUDIO_SAMPLE_RATE / AUDIO_CHUNK_FRAMES))
        if len(self._frames) < min_frames:
            logger.info(
                "[VoiceRecorder] Audio qua ngan (%d frames < %d min). Bo qua.",
                len(self._frames), min_frames
            )
            self._frames.clear()
            return None

        audio_bytes = b"".join(self._frames)
        self._frames.clear()
        logger.info("[VoiceRecorder] Tra ve %d bytes audio (%d frames).", len(audio_bytes), len(self._frames))
        return audio_bytes

    def cleanup(self) -> None:
        """Dong pyaudio an toan khi app thoat."""
        if self._pa:
            try:
                self._pa.terminate()
            except Exception as e:
                logger.error("[VoiceRecorder] Loi terminate pyaudio: %s", e, exc_info=True)
            finally:
                self._pa = None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _record_loop(self) -> None:
        """
        Thu am lien tuc va phat hien giong noi bang RMS don gian.
        Dung webrtcvad vi da xoa dependency, dung audioop.rms (Python built-in).
        """
        frames_per_sec = AUDIO_SAMPLE_RATE / AUDIO_CHUNK_FRAMES
        max_silence_frames = int(SILENCE_DURATION_SEC * frames_per_sec)
        min_speech_frames  = int(0.5 * frames_per_sec)
        max_total_frames   = int(RECORD_TIMEOUT_SEC * frames_per_sec)

        silence_count: int = 0
        speech_count: int  = 0
        has_spoken: bool   = False

        while self._is_recording and self._stream:
            try:
                data = self._stream.read(AUDIO_CHUNK_FRAMES, exception_on_overflow=False)
                self._frames.append(data)

                # Timeout bao hiem 30 giay
                if len(self._frames) > max_total_frames:
                    logger.warning("[VoiceRecorder] Timeout %ds. Tu dong ngat mic.", RECORD_TIMEOUT_SEC)
                    self._is_recording = False
                    if self._on_silence_detected:
                        self._on_silence_detected()
                    break

                # RMS VAD — simple nhung du dung voi PTT mode
                import audioop
                rms = audioop.rms(data, AUDIO_FORMAT_WIDTH)
                is_speech = rms > RMS_SPEECH_THRESHOLD

                if is_speech:
                    silence_count = 0
                    speech_count += 1
                    if speech_count >= min_speech_frames:
                        has_spoken = True
                else:
                    speech_count = 0
                    if has_spoken:
                        silence_count += 1

                # Tu dong ngat khi im lang du lau (chi cho VAD mode)
                if has_spoken and silence_count > max_silence_frames:
                    logger.info(
                        "[VoiceRecorder] Phat hien im lang > %.1fs. Tu dong ngat.",
                        SILENCE_DURATION_SEC
                    )
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


# ==============================================================================
#  GeminiSTT — Nhan dien giong noi bang Gemini Cloud API
# ==============================================================================

class GeminiSTT:
    """
    STT su dung Gemini API (gemini-3.1-flash-lite, audio inline).

    Uu diem so voi Whisper local:
      - Cold start = 0s (khong load model, khong subprocess)
      - RAM overhead = ~0 (Gemini la Cloud)
      - Toc do: 0.5-1s/request vs 3-10s (Whisper CPU)
      - Do chinh xac tieng Viet: cao hon (Gemini multilingual)

    Tuan thu ARCHITECTURE_RULES.md:
      - Thread-safe Singleton bang threading.Lock
      - gc.collect() sau moi lan transcribe (bat buoc boi production_check.py)
      - Khong goi tren Main Thread (chi tu VoiceWorker QThread)
    """

    _instance: Optional["GeminiSTT"] = None

    def __new__(cls) -> "GeminiSTT":
        with _gemini_stt_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._client = None
                cls._instance = inst
        return cls._instance

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_client(self):
        """Lazy-init Gemini client. Tai su dung ket noi tren moi lan goi."""
        if self._client is None:
            import google.genai as genai
            from src.shared.config import GEMINI_API_KEY
            api_key = GEMINI_API_KEY
            if not api_key:
                raise ValueError("[GeminiSTT] GEMINI_API_KEY chua duoc cau hinh trong .env")
            self._client = genai.Client(api_key=api_key)
            logger.info("[GeminiSTT] Gemini Client khoi tao thanh cong.")
        return self._client

    @staticmethod
    def _pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = AUDIO_SAMPLE_RATE) -> bytes:
        """
        Wrap raw PCM16 bytes vao WAV container trong bo nho.
        Khong cham disk — dung io.BytesIO.
        Gemini can WAV header de biet sample_rate va bit_depth.
        """
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(AUDIO_CHANNELS)
            wf.setsampwidth(AUDIO_FORMAT_WIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    # ── Public API ────────────────────────────────────────────────────────────

    def transcribe(self, audio_bytes: bytes) -> str:
        """
        Nhan dien giong noi tu raw PCM bytes.

        Args:
            audio_bytes: Raw PCM16, mono, 16000Hz (tu VoiceRecorder)

        Returns:
            Van ban tieng Viet. Tra ve "" neu khong nghe duoc.
            Tra ve chuoi bat dau bang "Loi:" neu co loi API.

        Luu y quan trong:
            - Phai goi tren Worker Thread (VoiceWorker), KHONG goi tren Main Thread.
            - gc.collect() duoc goi o cuoi (bat buoc boi production_check.py Rule).
        """
        from google.genai import types

        start_t = time.time()
        logger.info("[GeminiSTT] Bat dau transcribe %d bytes audio...", len(audio_bytes))

        try:
            # Wrap PCM -> WAV trong bo nho (khong I/O disk)
            wav_bytes = self._pcm_to_wav_bytes(audio_bytes)

            client = self._get_client()
            response = client.models.generate_content(
                model=GEMINI_STT_MODEL,
                contents=[
                    (
                        "Transcribe chinh xac doan audio tieng Viet sau. "
                        "Chi tra ve text thuan, khong them giai thich, "
                        "khong them dau ngoac kep, khong markdown. "
                        "Neu khong nghe ro hoac khong co giong noi, tra ve chuoi rong."
                    ),
                    types.Part.from_bytes(
                        data=wav_bytes,
                        mime_type="audio/wav",
                    ),
                ],
            )

            text = (response.text or "").strip()
            elapsed = time.time() - start_t
            logger.info("[GeminiSTT] Ket qua (%.2fs): '%s'", elapsed, text[:100])
            return text

        except ValueError as e:
            logger.error("[GeminiSTT] Loi cau hinh: %s", e, exc_info=True)
            return f"Loi: {str(e)[:100]}"
        except Exception as e:
            logger.error("[GeminiSTT] Loi API Gemini: %s", e, exc_info=True)
            return f"Loi nhan dien giong noi: {str(e)[:100]}"
        finally:
            # Bat buoc goi gc.collect() de giai phong bo nho
            # (yeu cau boi production_check.py Singleton & GC Enforcer Rule)
            gc.collect()
