# -*- coding: utf-8 -*-
import os
import json
import logging
import asyncio
import tempfile
from typing import Any, Callable, Dict, List, Optional
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, QUrl

import keyboard

from src.core.coordinator import RequestCoordinator

logger = logging.getLogger("Workers")

GLOBAL_HOTKEY = "ctrl+space"
VOICE_HOTKEY = "ctrl+shift+space"
TTS_MAX_CHARS = 800
TTS_VOICE = "vi-VN-NamMinhNeural"

try:
    import edge_tts as _edge_tts_mod
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False



class AIWorker(QThread):
    """
    Chay toan bo pipeline AI trong Worker Thread.
    Giao tiep voi Main Thread ONLY qua pyqtSignal.
    KHONG duoc dong vao bat ky widget Qt nao trong run().
    """
    sig_chunk = pyqtSignal(str)      # Delta text de danh may hien thi tren UI
    sig_sentence = pyqtSignal(str)   # Cau hoan chinh de day vao TTSWorker
    sig_finished = pyqtSignal(str)   # Phat ket qua tong ve Main Thread
    sig_error    = pyqtSignal(str)   # Phat thong bao loi

    def __init__(self, user_input: Any, process_fn: Callable, parent=None):
        super().__init__(parent)
        self._user_input = user_input
        self._process_fn = process_fn

    def run(self):
        """Chay trong Worker Thread. Khong goi widget method o day."""
        try:
            input_log = str(self._user_input)[:60]
            logger.info("[AIWorker] Bat dau xu ly: '%s'", input_log)
            gen = self._process_fn(self._user_input)
            
            full_text = ""
            sentence_buffer = ""
            import re
            
            for chunk in gen:
                if not self.isRunning():
                    break
                if chunk:
                    full_text += chunk
                    sentence_buffer += chunk
                    try:
                        self.sig_chunk.emit(chunk)
                    except RuntimeError:
                        break
                        
                    # Kiem tra ket thuc cau (dau cham, cham hoi, cham than theo sau boi khoang trang hoac xuong dong)
                    if re.search(r'[.?!](?:\s+|\n+|$)', sentence_buffer):
                        if len(sentence_buffer.strip()) > 10:
                            try:
                                self.sig_sentence.emit(sentence_buffer.strip())
                            except RuntimeError:
                                break
                            sentence_buffer = ""
            
            # Day not phan con lai trong buffer
            if sentence_buffer.strip():
                try:
                    self.sig_sentence.emit(sentence_buffer.strip())
                except RuntimeError:
                    pass

            logger.info("[AIWorker] Hoan thanh. Do dai: %d ky tu.", len(full_text))
            try:
                self.sig_finished.emit(full_text)
            except RuntimeError:
                pass
        except Exception as e:
            logger.error("[AIWorker] Loi: %s", e, exc_info=True)
            try:
                self.sig_error.emit(f"He thong gap su co: {str(e)[:120]}")
            except RuntimeError:
                pass


# ==============================================================================
#  TTSWorker - Worker Thread phat giong noi
# ==============================================================================

class TTSWorker(QThread):
    """
    Tai file MP3 tu Azure (edge-tts) trong Worker Thread.
    Cat text thanh tung cau nho va gui tung file MP3 (Streaming).
    """
    sig_chunk_ready = pyqtSignal(str)   # Duong dan MP3 cua 1 chunk
    sig_done = pyqtSignal()             # Da hoan thanh viec tai tat ca chunks

    def __init__(self, parent=None):
        super().__init__(parent)
        import queue
        self.queue = queue.Queue()
        self._is_running = True

    def add_sentence(self, sentence: str):
        self.queue.put(sentence)
        
    def stop(self):
        self._is_running = False
        self.queue.put(None)

    def run(self):
        if not _EDGE_TTS_AVAILABLE:
            logger.warning("[TTSWorker] edge-tts chua cai. Bo qua TTS.")
            try:
                self.sig_done.emit()
            except RuntimeError:
                pass
            return

        try:
            import queue
            import re
            
            async def _download_chunk(chunk_text):
                # Normalize date for Edge-TTS
                text_for_tts = re.sub(r'(\d{1,2})/(\d{1,2})/(\d{4})', r'ngày \1 tháng \2 năm \3', chunk_text)
                communicate = _edge_tts_mod.Communicate(text_for_tts, voice=TTS_VOICE)
                fd, path = tempfile.mkstemp(suffix=".mp3")
                os.close(fd)
                import time
                t0 = time.perf_counter()
                await communicate.save(path)
                tts_ms = (time.perf_counter() - t0) * 1000
                logger.info(f"[Metrics] TTS_chunk=%.0fms", tts_ms)
                return path

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            while True:
                try:
                    sentence = self.queue.get(timeout=0.5)
                except queue.Empty:
                    # Nếu queue rỗng VÀ có cờ báo ngưng (stop) thì thoát
                    if not self._is_running:
                        break
                    continue
                    
                if sentence is None:
                    break
                    
                # Không được check self.isRunning() ở đây vì QThread đã bị mark finished nếu main thread tắt
                # Chúng ta dựa vào cờ self._is_running và việc xả cạn queue.
                    
                try:
                    path = loop.run_until_complete(_download_chunk(sentence))
                    logger.debug("[TTSWorker] Chunk MP3 tai xong: %s", path)
                    try:
                        self.sig_chunk_ready.emit(path)
                    except RuntimeError:
                        break
                except Exception as e:
                    logger.warning(f"[TTSWorker] Loi tai chunk TTS: {e}")
                    continue
            
            loop.close()
            try:
                self.sig_done.emit()
            except RuntimeError:
                pass
        except Exception as e:
            logger.error("[TTSWorker] Loi tai TTS: %s", e, exc_info=True)
            try:
                self.sig_done.emit()
            except RuntimeError:
                pass


# ==============================================================================
#  VoiceWorker - Worker Thread xu ly STT (Gemini Cloud API)
# ==============================================================================

class VoiceWorker(QThread):
    """
    Worker thuc hien STT bang Gemini Cloud API (gemini-3.5-flash-lite).
    Nhan raw PCM bytes tu VoiceRecorder, khong can file tam tren disk.
    Tranh block giao dien bang cach chay trong Worker Thread rieng biet.
    """
    sig_finished = pyqtSignal(str)   # Phat text giai ma ve Main Thread

    def __init__(self, audio_bytes: bytes, parent=None):
        super().__init__(parent)
        self._audio_bytes = audio_bytes

    def run(self) -> None:
        try:
            from src.ui.voice_engine import GeminiLiveSTT, GeminiSTT
            import time

            t0 = time.perf_counter()

            # Dung GeminiLiveSTT (ISTTProvider streaming-first)
            live_stt = GeminiLiveSTT()
            live_stt.start()
            live_stt.push(self._audio_bytes)  # PCM bytes da buffer san tu VoiceRecorder
            live_stt.stop()
            text = live_stt.get_transcript()

            stt_ms = (time.perf_counter() - t0) * 1000
            logger.info("[Metrics] GeminiLive STT=%.0fms", stt_ms)

            # Fallback sang GeminiSTT batch neu Live tra ve rong
            if not text:
                logger.warning("[VoiceWorker] GeminiLive tra ve rong, thu GeminiSTT batch...")
                batch_stt = GeminiSTT()
                text = batch_stt.transcribe(self._audio_bytes)

            try:
                self.sig_finished.emit(text if text else "Lỗi: STT trả về kết quả trống.")
            except RuntimeError:
                pass

        except ImportError as e:
            logger.error("[VoiceWorker] Thieu thu vien voice_engine: %s", e, exc_info=True)
            try:
                self.sig_finished.emit("Lỗi: Không tìm thấy engine STT.")
            except RuntimeError:
                pass
        except Exception as e:
            logger.error("[VoiceWorker] Loi: %s", e, exc_info=True)
            try:
                self.sig_finished.emit(f"Lỗi giải mã: {str(e)[:80]}")
            except RuntimeError:
                pass


# ==============================================================================
#  GlobalHotkeyWorker - Lang nghe phim tat toan cuc
# ==============================================================================

class GlobalHotkeyWorker(QThread):
    """
    Lang nghe phim tat Ctrl+Space toan cuc trong Worker Thread rieng.
    keyboard.wait() la ham blocking -> PHAI chay trong thread rieng.

    Yeu cau: Chay Python voi quyen Administrator tren Windows.
    Neu khong co quyen -> log warning, khong crash.

    [BUG-11 FIX] Them flag _running va phuong thuc stop() de dung sach.
    keyboard.unhook_all() giai phong hook truoc khi thread ket thuc.
    """
    sig_toggle = pyqtSignal()    # Phat ve Main Thread khi hotkey duoc bam
    sig_voice = pyqtSignal()     # Phat ve khi bam Alt+Space (Voice Mode - VAD toggle)
    sig_ptt_start = pyqtSignal() # [S2-PTT] Phat khi bat dau giu phim (PTT Mode)
    sig_ptt_stop  = pyqtSignal() # [S2-PTT] Phat khi tha phim (PTT Mode)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        # Set daemon to True to prevent zombie process if app crashes
        self.setTerminationEnabled(True)

    def stop_listening(self):
        """Dung sach hotkey hook. Goi tu Main Thread truoc khi app thoat."""
        self._running = False
        try:
            import keyboard
            keyboard.unhook_all()   # Giai phong tat ca hook -> keyboard.wait() se return
            logger.info("[Hotkey] Da giai phong keyboard hooks.")
        except Exception as e:
            logger.debug("[Hotkey] Loi unhook keyboard: %s", e)

    def run(self):
        try:
            import keyboard

            def _on_hotkey():
                logger.info("[Hotkey] %s bam -> toggle_signal.", GLOBAL_HOTKEY)
                try:
                    self.sig_toggle.emit()
                except RuntimeError:
                    pass

            # [S2-PTT] Doc VOICE_MODE tu bien moi truong
            # ptt = Push-to-Talk (giu phim = ghi, tha phim = gui)
            # vad = VAD tu dong (bam 1 lan de bat/tat, hien tai la mode mac dinh)
            from src.shared.config import VOICE_MODE
            voice_mode = VOICE_MODE.strip().lower()
            logger.info("[Hotkey] Voice Mode: %s", voice_mode.upper())

            keyboard.add_hotkey(GLOBAL_HOTKEY, _on_hotkey)

            if voice_mode == "ptt":
                # [S2-PTT] Push-to-Talk: theo doi press va release cua Alt+Space
                _ptt_active = False

                def _on_key_press(event):
                    nonlocal _ptt_active
                    if event.name == 'space' and keyboard.is_pressed('alt'):
                        if not _ptt_active:
                            _ptt_active = True
                            logger.info("[Hotkey] [PTT] Giu phim -> ptt_start.")
                            try:
                                self.sig_ptt_start.emit()
                            except RuntimeError:
                                pass

                def _on_key_release(event):
                    nonlocal _ptt_active
                    if event.name in ('space', 'alt') and _ptt_active:
                        _ptt_active = False
                        logger.info("[Hotkey] [PTT] Tha phim -> ptt_stop.")
                        try:
                            self.sig_ptt_stop.emit()
                        except RuntimeError:
                            pass

                keyboard.on_press(_on_key_press)
                keyboard.on_release(_on_key_release)
                logger.info("[Hotkey] Dang lang nghe %s (PTT) va %s.", VOICE_HOTKEY, GLOBAL_HOTKEY)
            else:
                # VAD mode giu nguyen logic cu (toggle)
                def _on_voice_hotkey():
                    logger.info("[Hotkey] %s bam -> voice_signal.", VOICE_HOTKEY)
                    try:
                        self.sig_voice.emit()
                    except RuntimeError:
                        pass

                keyboard.add_hotkey(VOICE_HOTKEY, _on_voice_hotkey)
                logger.info("[Hotkey] Dang lang nghe %s va %s (can quyen Admin).", GLOBAL_HOTKEY, VOICE_HOTKEY)

            keyboard.wait()  # Blocking: giu thread song - se return khi unhook_all() duoc goi

        except ImportError:
            logger.warning("[Hotkey] Thu vien 'keyboard' chua cai. Hotkey bi tat.")
        except Exception as e:
            logger.error("[Hotkey] Loi: %s. Hotkey bi tat.", e, exc_info=True)
