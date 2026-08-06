"""
voice_engine.py - Voice Mode STT (Sprint 1 Refactored)
=======================================================
Kien truc:
  VoiceRecorder  : pyaudio ghi am, RMS VAD phat hien am thanh.
                   stop_recording() tra ve raw PCM bytes.

  GeminiSTT      : Batch STT (fallback). Singleton thread-safe.
                   Nhan PCM bytes -> wrap WAV -> gui Gemini -> tra text.

  GeminiLiveSTT  : STT dung Gemini Live API (Sprint 1).
                   Singleton Client module-level (tranh tao moi TLS/Auth).
                   Timeout 15s, Selective Retry (429/503/timeout only).
                   Metrics log: prepare | gemini | total.

Tuan thu:
  - gc.collect() bat buoc sau moi transcribe (production_check.py Rule)
  - Thread-safe Singleton bang threading.Lock
  - Khong goi blocking API tren Main Thread
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
AUDIO_CHUNK_FRAMES    = 480    # 30ms tai 16000Hz
AUDIO_FORMAT_WIDTH    = 2      # int16 = 2 bytes/sample
AUDIO_CHANNELS        = 1      # mono
AUDIO_SAMPLE_RATE     = 16000  # Hz
SILENCE_DURATION_SEC  = 1.5    # Giay im lang de tu dong ngat mic
MIN_AUDIO_DURATION    = 1.5    # Giay toi thieu (ngay hon bi bo qua)
RECORD_TIMEOUT_SEC    = 30     # Giay toi da ghi am
RMS_SPEECH_THRESHOLD  = 300    # Nguong RMS phan biet tieng noi vs tieng on
GEMINI_STT_MODEL      = "gemini-3.5-flash-lite"
GEMINI_LIVE_MODEL     = "gemini-live-2.5-flash-preview"

# ── Singleton lock cho GeminiSTT (batch) ──────────────────────────────────────
_gemini_stt_lock = threading.Lock()


# ==============================================================================
#  CancelToken — Sprint 2
# ==============================================================================

class CancelToken:
    """
    Token huy request. Truyen vao GeminiLiveSTT.get_transcript().
    VoiceWorker.cancel() goi cancel() de dung Gemini loop ngay lap tuc.
    Thread-safe: dung threading.Event.
    """
    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        """Kich hoat huy. Safe khi goi nhieu lan."""
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        """Dat lai trang thai de tai su dung token."""
        self._event.clear()


# ==============================================================================
#  VoiceRecorder — Thu am tu microphone
# ==============================================================================

class VoiceRecorder:
    """
    Ghi am tu microphone, su dung RMS don gian de phat hien giong noi.

    stop_recording() tra ve Optional[bytes] (raw PCM16, khong luu file).
    VAD: audioop.rms (built-in Python, khong can webrtcvad).
    """

    def __init__(self, on_silence_detected: Optional[callable] = None,
                 on_chunk: Optional[callable] = None):
        import pyaudio
        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._frames: list[bytes] = []
        self._is_recording: bool = False
        self._record_thread: Optional[threading.Thread] = None
        self._on_silence_detected = on_silence_detected
        self._on_chunk = on_chunk  # Sprint 3: callback nhan tung chunk de push real-time
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
        Tra ve None neu: khong co du lieu hoac audio qua ngan.
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

        min_frames = int(MIN_AUDIO_DURATION * (AUDIO_SAMPLE_RATE / AUDIO_CHUNK_FRAMES))
        if len(self._frames) < min_frames:
            logger.info(
                "[VoiceRecorder] Audio qua ngan (%d frames < %d min). Bo qua.",
                len(self._frames), min_frames
            )
            self._frames.clear()
            return None

        audio_bytes = b"".join(self._frames)
        n_frames = len(self._frames)
        self._frames.clear()
        logger.info("[VoiceRecorder] Tra ve %d bytes audio (%d frames).", len(audio_bytes), n_frames)
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

    # ── Private ───────────────────────────────────────────────────────────────

    def _record_loop(self) -> None:
        """Thu am lien tuc, phat hien giong noi bang RMS VAD."""
        frames_per_sec     = AUDIO_SAMPLE_RATE / AUDIO_CHUNK_FRAMES
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
                # Sprint 3: push chunk ngay lap tuc sang GeminiLiveSTT
                if self._on_chunk:
                    try:
                        self._on_chunk(data)
                    except Exception as _e:
                        logger.debug("[VoiceRecorder] on_chunk error: %s", _e)

                if len(self._frames) > max_total_frames:
                    logger.warning("[VoiceRecorder] Timeout %ds. Tu dong ngat mic.", RECORD_TIMEOUT_SEC)
                    self._is_recording = False
                    if self._on_silence_detected:
                        self._on_silence_detected()
                    break

                import audioop
                rms       = audioop.rms(data, AUDIO_FORMAT_WIDTH)
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
#  GeminiSTT — Batch STT (Fallback)
# ==============================================================================

class GeminiSTT:
    """
    STT batch dung Gemini API (gemini-3.5-flash-lite).
    Dung lam fallback khi GeminiLiveSTT tra ve rong hoac loi khong retry duoc.
    Thread-safe Singleton.
    """

    _instance: Optional["GeminiSTT"] = None

    def __new__(cls) -> "GeminiSTT":
        with _gemini_stt_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._client = None
                cls._instance = inst
        return cls._instance

    def _get_client(self):
        if self._client is None:
            import google.genai as genai
            from src.shared.config import GEMINI_API_KEY
            if not GEMINI_API_KEY:
                raise ValueError("[GeminiSTT] GEMINI_API_KEY chua duoc cau hinh trong .env")
            self._client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("[GeminiSTT] Gemini Client khoi tao.")
        return self._client

    @staticmethod
    def _pcm_to_wav_bytes(pcm_bytes: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(AUDIO_CHANNELS)
            wf.setsampwidth(AUDIO_FORMAT_WIDTH)
            wf.setframerate(AUDIO_SAMPLE_RATE)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe PCM bytes -> text. Chi goi tu VoiceWorker (QThread)."""
        from google.genai import types

        t0 = time.perf_counter()
        logger.info("[GeminiSTT] Batch transcribe %d bytes...", len(audio_bytes))
        try:
            wav_bytes = self._pcm_to_wav_bytes(audio_bytes)
            client    = self._get_client()
            response  = client.models.generate_content(
                model=GEMINI_STT_MODEL,
                contents=[
                    (
                        "Transcribe chinh xac doan audio tieng Viet sau. "
                        "Chi tra ve text thuan, khong them giai thich, "
                        "khong markdown. Neu khong nghe ro, tra ve chuoi rong."
                    ),
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                ],
            )
            text    = (response.text or "").strip()
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info("[Metrics] GeminiSTT batch: %.0fms | '%s'", elapsed, text[:60])
            return text
        except Exception as e:
            logger.error("[GeminiSTT] Loi API: %s", e, exc_info=True)
            return f"Loi: {str(e)[:100]}"
        finally:
            gc.collect()


# ==============================================================================
#  GeminiLiveSTT — Gemini Live API STT
#  Sprint 1: Singleton Client + Timeout + Selective Retry + Metrics
# ==============================================================================

# ── Module-level Singleton Client ─────────────────────────────────────────────
# Chia se ket noi giua cac lan PTT, tranh tao moi TLS/Auth moi lan (~200ms).
_LIVE_CLIENT_LOCK = threading.Lock()
_LIVE_CLIENT: Optional[object] = None


def _get_live_client():
    """
    Tra ve Gemini Client duy nhat cua toan module (Singleton).
    Thread-safe: chi tao 1 lan du nhieu VoiceWorker goi dong thoi.
    """
    global _LIVE_CLIENT
    with _LIVE_CLIENT_LOCK:
        if _LIVE_CLIENT is None:
            import google.genai as genai
            from src.shared.config import GEMINI_API_KEY
            if not GEMINI_API_KEY:
                raise ValueError("[GeminiLiveSTT] GEMINI_API_KEY chua cau hinh trong .env")
            _LIVE_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("[GeminiLiveSTT] Singleton Client khoi tao.")
        return _LIVE_CLIENT


def prewarm_client() -> None:
    """
    Khoi tao Singleton Client som (goi tai app startup).
    Muc tieu: TLS handshake xay ra 1 lan khi app load, khong phai khi PTT lan dau.
    An toan khi goi nhieu lan hoac khi API key chua san sang (log warning, khong crash).
    """
    try:
        _get_live_client()
        logger.info("[prewarm_client] Gemini Live client da warm xong.")
    except Exception as e:
        logger.warning("[prewarm_client] Khong the warm client: %s", e)


# ── Phan loai loi de Selective Retry ─────────────────────────────────────────
# Chi retry loi tam thoi (mang, rate limit).
# Khong retry loi logic (auth, audio sai) de tranh loop vo ich va che giau bug.
_RETRYABLE_HTTP_CODES = {429, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    """True = retry duoc, False = dung ngay."""
    import asyncio
    msg = str(exc).lower()

    if isinstance(exc, asyncio.TimeoutError):
        return True
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
        return True
    for code in _RETRYABLE_HTTP_CODES:
        if str(code) in msg:
            return True

    # Loi logic/quyen -> KHONG retry
    for sig in ("401", "403", "invalid_argument", "permission",
                 "invalid audio", "unauthenticated"):
        if sig in msg:
            return False

    return True  # Mac dinh: retry cho loi chua xac dinh


class GeminiLiveSTT:
    """
    STT dung Gemini Live API.

    Sprint 1: Singleton Client + Timeout + Selective Retry + Metrics
    Sprint 2: CancelToken (kiem tra trong recv loop va giua retries)
    Sprint 3: True Streaming — audio duoc gui chunk-by-chunk TRONG KHI ghi am.

    Hai che do hoat dong:
      BATCH mode (Sprint 1/2): push() buffer, get_transcript() gui 1 lan
      STREAMING mode (Sprint 3): start() mo session, push() gui ngay, get_transcript() cho ket qua

    Speculative Retrieval (Sprint 3):
      on_partial(partial_text): callback khi partial transcript dat nguong token.
      Caller co the bat dau RAG warm-up som, giam latency tong the.
    """

    _MAX_RETRIES  = 2
    _RETRY_DELAYS = (1.0, 2.0)
    _STT_TIMEOUT  = 15.0

    # Keepalive: gui PCM silence neu queue idle qua lau de giu connection song
    _SENDER_KEEPALIVE_SEC  = 8     # giay cho queue truoc khi gui silence
    _SENDER_KEEPALIVE_MAX  = 3     # so lan gui silence toi da (8s x 3 = 24s)
    # Silence chunk: 30ms PCM16 zero (16000 * 0.03 * 2 bytes = 960 bytes)
    _SILENCE_CHUNK = b'\x00' * (AUDIO_CHUNK_FRAMES * AUDIO_FORMAT_WIDTH)

    # Speculative Retrieval: dung stability check, KHONG dung char threshold
    # Xem _is_query_stable() de biet logic phan loai

    def __init__(self):
        # BATCH mode state
        self._chunks: list[bytes] = []
        self._lock   = threading.Lock()

        # STREAMING mode state (Sprint 3)
        self._stream_mode    = False
        self._audio_queue: Optional[object] = None   # asyncio.Queue
        self._transcript_parts: list[str]   = []
        self._done_event     = threading.Event()
        self._session_error: Optional[Exception] = None
        self._loop: Optional[object] = None          # asyncio event loop
        self._loop_thread: Optional[threading.Thread] = None
        self._ready_event    = threading.Event()
        self._on_partial     = None   # callback(partial_text: str) -> None
        self._speculative_fired = False

    # ── Sprint 3: True Streaming API ─────────────────────────────────────────

    def set_on_partial(self, callback) -> None:
        """
        Dat callback cho Speculative Retrieval.
        callback(partial_text: str) duoc goi khi partial transcript dat nguong.
        """
        self._on_partial = callback

    def start_streaming(self, cancel_token=None) -> None:
        """
        [Sprint 3] Mo asyncio event loop + Gemini Live session trong thread rieng.
        Phai goi TRUOC khi ghi am bat dau.
        VoiceRecorder se goi push() moi 30ms chunk.

        Args:
            cancel_token: CancelToken de dung streaming giua chung.
        """
        import asyncio

        self._stream_mode = True
        self._chunks      = []
        self._transcript_parts = []
        self._done_event.clear()
        self._ready_event.clear()
        self._session_error = None
        self._speculative_fired = False
        self._cancel_token = cancel_token

        # Tao asyncio event loop chay trong thread rieng (tranh xung dot Qt loop)
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_event_loop, daemon=True, name="GeminiLiveLoop"
        )
        self._loop_thread.start()

        # Bat dau session trong loop (dua vao thread de xu ly)
        import asyncio as _asyncio
        _asyncio.run_coroutine_threadsafe(self._open_stream_session(), self._loop)

        # Doi session mo xong (toi da 5 giay)
        if not self._ready_event.wait(timeout=5.0):
            logger.error("[GeminiLiveSTT] Timeout mo Live session (5s).")
            self._stream_mode = False
            raise RuntimeError("[GeminiLiveSTT] Khong the mo Live session.")
        logger.info("[GeminiLiveSTT] True streaming session da san sang.")

    def _run_event_loop(self) -> None:
        """Chay asyncio loop trong thread rieng (co the bi dung qua loop.call_soon_threadsafe)."""
        import asyncio
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _open_stream_session(self) -> None:
        """Coroutine chinh: mo session, chay sender + receiver dong thoi."""
        import asyncio
        from google.genai import types as genai_types
        from src.ui.voice_errors import VoiceCancelledError

        try:
            self._audio_queue = asyncio.Queue(maxsize=32)
            client = _get_live_client()
            config = genai_types.LiveConnectConfig(
                response_modalities=["TEXT"],
                system_instruction=(
                    "Ban la he thong nhan dang giong noi tieng Viet chinh xac. "
                    "Chi tra ve van ban thuan tu doan audio, khong them giai thich, "
                    "khong markdown. Neu khong co giong noi, tra ve chuoi rong."
                ),
            )

            async with client.aio.live.connect(
                model=GEMINI_LIVE_MODEL, config=config,
            ) as session:
                self._ready_event.set()  # Signal cho start_streaming() biet session da mo

                sender_task   = asyncio.create_task(self._sender(session))
                receiver_task = asyncio.create_task(self._receiver(session))
                await asyncio.gather(sender_task, receiver_task)

        except Exception as exc:
            self._session_error = exc
            logger.error("[GeminiLiveSTT] Stream session error: %s", exc, exc_info=True)
        finally:
            self._done_event.set()
            # Dung loop sau khi xong
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _sender(self, session) -> None:
        """
        Task gui: doc chunk tu queue, gui PCM len Gemini real-time.

        Keepalive: neu queue idle qua _SENDER_KEEPALIVE_SEC giay,
        gui silence PCM de giu connection song (tranh Gemini dong session).
        Sau _SENDER_KEEPALIVE_MAX lan im lang lien tiep -> dong.
        """
        import asyncio
        from google.genai import types as genai_types

        keepalive_count = 0

        while True:
            try:
                chunk = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=self._SENDER_KEEPALIVE_SEC,
                )
            except asyncio.TimeoutError:
                # Queue idle -> kiem tra co nen keepalive khong
                if keepalive_count >= self._SENDER_KEEPALIVE_MAX:
                    logger.warning(
                        "[GeminiLiveSTT] Sender idle %.0fs x %d lan. Dong session.",
                        self._SENDER_KEEPALIVE_SEC, self._SENDER_KEEPALIVE_MAX,
                    )
                    break
                # Gui silence de giu connection
                keepalive_count += 1
                logger.debug("[GeminiLiveSTT] Keepalive #%d gui silence.", keepalive_count)
                try:
                    await session.send(
                        input=genai_types.Blob(
                            data=self._SILENCE_CHUNK,
                            mime_type=f"audio/pcm;rate={AUDIO_SAMPLE_RATE}",
                        )
                    )
                except Exception as e:
                    logger.warning("[GeminiLiveSTT] Keepalive send error: %s", e)
                    break
                continue

            # Audio that den -> reset keepalive counter
            keepalive_count = 0

            if chunk is None:  # Sentinel -> ket thuc turn
                try:
                    await session.send(end_of_turn=True)
                except Exception as e:
                    logger.debug("[GeminiLiveSTT] Sender end_of_turn error: %s", e)
                break

            if self._cancel_token and self._cancel_token.is_cancelled():
                break

            try:
                await session.send(
                    input=genai_types.Blob(
                        data=chunk,
                        mime_type=f"audio/pcm;rate={AUDIO_SAMPLE_RATE}",
                    )
                )
            except Exception as e:
                logger.warning("[GeminiLiveSTT] Sender error: %s", e)
                break

    async def _receiver(self, session) -> None:
        """
        Task nhan: thu partial transcript, goi on_partial khi query on dinh.

        Speculative Retrieval dung Query Stability, KHONG dung char threshold:
          - Phai co >= 4 tu (y dinh da hinh thanh)
          - Tu cuoi KHONG phai 'dangling word' (biet la query chua hoan chinh)
          - Velocity trung binh < 15 chars/update (user da giam toc, sap xong noi)
        """
        partial_so_far  = ""
        partial_history: list[str] = []   # rolling window de tinh velocity

        async for response in session.receive():
            if self._cancel_token and self._cancel_token.is_cancelled():
                logger.info("[GeminiLiveSTT] Receiver: cancel token set, dung.")
                break
            if response.text:
                self._transcript_parts.append(response.text)
                partial_so_far += response.text
                partial_history.append(partial_so_far)

                # Speculative Retrieval: trigger khi query on dinh
                if (self._on_partial and not self._speculative_fired
                        and self._is_query_stable(partial_so_far, partial_history)):
                    self._speculative_fired = True
                    logger.info("[GeminiLiveSTT] Speculative trigger (stable): '%s'",
                                partial_so_far[:50])
                    try:
                        self._on_partial(partial_so_far)
                    except Exception as e:
                        logger.debug("[GeminiLiveSTT] on_partial error: %s", e)

    @staticmethod
    def _is_query_stable(partial: str, history: list[str]) -> bool:
        """
        Kiem tra query da on dinh de bat dau speculative retrieval chua.

        Logic (theo thu tu priority):
          1. < 4 tu: qua ngan, y dinh chua ro -> False
          2. Tu cuoi la 'dangling word': user chua noi xong -> False
          3. Velocity cao (> 15 chars/update trung binh): user dang noi nhanh -> False
          4. Tat ca dieu kien qua -> True, co the prefetch

        Vi du:
          'So sanh phuong'        -> False (phuong la dangling)
          'So sanh phuong phap'   -> False (phap la dangling)
          'So sanh phuong phap RLHF voi DPO' -> True
        """
        words = partial.strip().split()

        # Dieu kien 1: qua it tu
        if len(words) < 4:
            return False

        # Dieu kien 2: tu cuoi la tu 'treo' (query chua hoan chinh)
        # Bao gom tieng Viet va tieng Anh pho bien
        DANGLING = {
            # Tieng Viet
            'va', 'voi', 'cua', 'la', 'co', 'nhu', 'so', 'trong',
            've', 'phuong', 'theo', 'cac', 'nhung', 'mot', 'do',
            'nay', 'khi', 'neu', 'de', 'giua', 'den', 'tu', 'cho',
            'ma', 'hay', 'hoac', 'bi', 'duoc', 'se', 'da', 'dang',
            'ban', 'ta', 'minh', 'gi', 'the', 'nao', 'sao',
            # Tieng Anh (user co the hoi bang ca hai)
            'and', 'or', 'but', 'with', 'the', 'a', 'an', 'of',
            'in', 'on', 'at', 'to', 'for', 'by', 'from', 'that',
            'which', 'between', 'compare', 'versus', 'vs',
        }
        last_word = words[-1].lower().rstrip('.,!?;:')
        if last_word in DANGLING:
            return False

        # Dieu kien 3: velocity check
        # Neu growth rate cao -> user van noi nhieu -> chua on dinh
        if len(history) >= 3:
            recent  = history[-3:]
            growth  = [len(recent[i]) - len(recent[i - 1]) for i in range(1, len(recent))]
            avg_growth = sum(growth) / len(growth)
            if avg_growth > 15:  # >15 chars/update = dang noi nhanh
                return False

        return True

    # ── BATCH mode API (Sprint 1/2, tuong thich nguoc) ────────────────────────

    def start(self) -> None:
        """[Batch mode] Reset buffer am thanh cho session moi."""
        self._stream_mode = False
        with self._lock:
            self._chunks = []

    def push(self, chunk: bytes) -> None:
        """
        [Unified] Gui chunk:
          - Batch mode: buffer vao list (goi get_transcript() sau)
          - Streaming mode: gui ngay qua asyncio Queue den Gemini
        """
        if self._stream_mode and self._loop and self._audio_queue:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                self._audio_queue.put(chunk), self._loop
            )
        else:
            with self._lock:
                self._chunks.append(chunk)

    def stop(self) -> None:
        """
        [Unified] Ket thuc ghi am:
          - Streaming mode: gui sentinel None vao queue (ket thuc sender)
          - Batch mode: log stats
        """
        if self._stream_mode and self._loop and self._audio_queue:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                self._audio_queue.put(None), self._loop
            )
            logger.info("[GeminiLiveSTT] Stream stop signal gui.")
        else:
            logger.debug("[GeminiLiveSTT] Batch stop() — %d chunks buffered.", len(self._chunks))

    def get_transcript(self, cancel_token=None) -> str:
        """
        [Unified] Tra ve transcript cuoi cung.

        Streaming mode: cho done_event (session da nhan het response tu Gemini).
        Batch mode    : gom buffer -> WAV -> gui Gemini Live -> retry neu can.

        Args:
            cancel_token: CancelToken (Sprint 2). Kiem tra truoc moi retry.
        """
        if self._stream_mode:
            return self._get_transcript_streaming(cancel_token)
        return self._get_transcript_batch(cancel_token)

    def _get_transcript_streaming(self, cancel_token=None) -> str:
        """[Sprint 3] Cho session xong roi tra transcript da tich luy."""
        from src.ui.voice_errors import VoiceCancelledError

        # Cho done_event voi timeout 20s
        if not self._done_event.wait(timeout=20.0):
            logger.error("[GeminiLiveSTT] Timeout cho stream session (20s).")
            return ""

        if cancel_token and cancel_token.is_cancelled():
            raise VoiceCancelledError("User huy (streaming mode)")

        if self._session_error:
            logger.error("[GeminiLiveSTT] Session error: %s", self._session_error)
            return ""

        transcript = "".join(self._transcript_parts).strip()
        logger.info("[GeminiLiveSTT][Stream] Final transcript: '%s'", transcript[:60])
        return transcript

    def _get_transcript_batch(self, cancel_token=None) -> str:
        """[Sprint 1/2 Batch] Gom buffer -> WAV -> Gemini -> retry neu can."""
        import asyncio
        from src.ui.voice_errors import VoiceCancelledError

        with self._lock:
            chunks_copy = list(self._chunks)

        if not chunks_copy:
            logger.warning("[GeminiLiveSTT] Khong co audio.")
            return ""

        total_frames = sum(len(c) for c in chunks_copy) // AUDIO_FORMAT_WIDTH
        min_frames   = int(MIN_AUDIO_DURATION * AUDIO_SAMPLE_RATE)
        if total_frames < min_frames:
            logger.info("[GeminiLiveSTT] Audio qua ngan (%d/%d frames). Bo qua.",
                        total_frames, min_frames)
            return ""

        t_prepare  = time.perf_counter()
        wav_data   = self._chunks_to_wav(chunks_copy)
        prepare_ms = (time.perf_counter() - t_prepare) * 1000
        audio_sec  = total_frames / AUDIO_SAMPLE_RATE
        logger.info("[GeminiLiveSTT] Batch: gui %.1fs audio (%d bytes WAV)...", audio_sec, len(wav_data))

        last_exc = None
        for attempt in range(self._MAX_RETRIES + 1):
            if cancel_token and cancel_token.is_cancelled():
                raise VoiceCancelledError("User huy")

            t_api = time.perf_counter()
            try:
                loop = asyncio.new_event_loop()
                try:
                    transcript = loop.run_until_complete(
                        asyncio.wait_for(
                            self._transcribe_async(wav_data, cancel_token=cancel_token),
                            timeout=self._STT_TIMEOUT,
                        )
                    )
                finally:
                    loop.close()

                gemini_ms = (time.perf_counter() - t_api) * 1000
                total_ms  = prepare_ms + gemini_ms
                logger.info(
                    "[Metrics] STT batch: prepare=%.0fms | gemini=%.0fms | total=%.0fms | '%s'",
                    prepare_ms, gemini_ms, total_ms, transcript[:60]
                )
                gc.collect()
                return transcript

            except Exception as exc:
                last_exc = exc
                if isinstance(exc, VoiceCancelledError):
                    raise
                if not _is_retryable(exc):
                    logger.error("[GeminiLiveSTT] Loi khong retry duoc (%s): %s",
                                 type(exc).__name__, exc)
                    break
                if attempt < self._MAX_RETRIES:
                    delay = self._RETRY_DELAYS[attempt]
                    logger.warning(
                        "[GeminiLiveSTT] Retry %d/%d [%s] sau %.0fs...",
                        attempt + 1, self._MAX_RETRIES, type(exc).__name__, delay
                    )
                    time.sleep(delay)
                else:
                    logger.error("[GeminiLiveSTT] Het retry. Loi: %s", last_exc)

        gc.collect()
        return ""

    # ── Shared helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _chunks_to_wav(chunks: list[bytes]) -> bytes:
        """Ghep PCM chunks thanh WAV (chi dung trong batch mode)."""
        pcm = b"".join(chunks)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(AUDIO_CHANNELS)
            wf.setsampwidth(AUDIO_FORMAT_WIDTH)
            wf.setframerate(AUDIO_SAMPLE_RATE)
            wf.writeframes(pcm)
        return buf.getvalue()

    async def _transcribe_async(self, wav_bytes: bytes,
                                cancel_token=None) -> str:
        """Batch coroutine: gui WAV, nhan transcript, kiem tra cancel."""
        from google.genai import types as genai_types
        from src.ui.voice_errors import VoiceCancelledError

        client = _get_live_client()
        config = genai_types.LiveConnectConfig(
            response_modalities=["TEXT"],
            system_instruction=(
                "Ban la he thong nhan dang giong noi tieng Viet chinh xac. "
                "Chi tra ve van ban thuan tu doan audio, khong them giai thich, "
                "khong markdown, khong dau ngoac kep. "
                "Neu khong co giong noi hoac am thanh qua ngan, tra ve chuoi rong."
            ),
        )

        transcript = ""
        async with client.aio.live.connect(
            model=GEMINI_LIVE_MODEL, config=config,
        ) as session:
            await session.send(
                input=genai_types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                end_of_turn=True,
            )
            async for response in session.receive():
                if cancel_token and cancel_token.is_cancelled():
                    raise VoiceCancelledError("User huy trong receive loop")
                if response.text:
                    transcript += response.text

        return transcript.strip()

