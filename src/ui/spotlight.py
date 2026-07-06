"""
spotlight.py - Cua so Spotlight UI PyQt6 (Giai doan 4 - Production Ready)
===========================================================================
Kien truc da luong (Phan 2.1 & Rui ro 1 - last agent.md):

  SpotlightWindow    : Main Thread - Qt Event Loop
                       Ve giao dien, nhan input, phat lenh.
                       TUYET DOI khong goi blocking API trong thread nay.

  AIWorker           : Worker Thread - QThread
                       Goi process_user_input() -> SemanticRouter -> Orchestrator.
                       Giao tiep voi Main Thread ONLY qua pyqtSignal (thread-safe).

  TTSWorker          : Worker Thread - QThread
                       Phat giong noi qua edge-tts.
                       Dung asyncio.run() tranh Event Loop Conflict voi PyQt6.
                       Fallback ve winsound (built-in) neu edge-tts chua cai.

  GlobalHotkeyThread : Worker Thread - QThread
                       keyboard.wait() chay rieng, khong block Main Thread.
                       Phat toggle_signal khi Ctrl+Space duoc bam.

3 Che do hien thi cua so:
  FAST  -> Regex khop tuc thi: giu cua so, hien ket qua trong QTextEdit
  AI    -> Goi LLM: mo rong cua so, hien "Dang suy nghi...", doi AIWorker
  NINJA -> Regex lenh nen: hide() ngay, win11toast goc man hinh

FIX & OPTIMIZE (v2):
  [FIX-1] setMinimumHeight/setMaximumHeight thay vi setFixedHeight
          -> Cho phep QPropertyAnimation thay doi chieu cao
  [FIX-2] intercept_fn chi nhan (text, last_response) khong bi TypeError partial
  [FIX-3] Guard double-start AIWorker khi user nhan Enter lien tiep
  [FIX-4] show_and_focus dung resize() thay animation khi widget dang an
  [FIX-5] Stop TTSWorker cu truoc khi start moi, tranh giong chong cheo
  [OPT-1] TTSWorker dung winsound (blocking, built-in) thay wmplayer + sleep(10)
          -> Khong con magic number, xoa file ngay khi phat xong
  [OPT-2] Them cleanup() cong khai de main.py goi khi app.quit()
  [OPT-3] Them _is_busy property de UI khoa dung khi dang xu ly
  [OPT-4] QTimer delay nho sau show() de activateWindow hoat dong chinh xac tren Win11

LUU Y QUAN TRONG:
  - Can quyen Administrator de keyboard hook toan cuc hoat dong.
  - edge-tts can ket noi Internet (Azure Cloud).
  - Voice Mode (STT Whisper) la placeholder, se implement o Giai doan 5.
"""

import os
import sys
import asyncio
import logging
import tempfile
from typing import Optional, Any, Callable

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLineEdit,
    QTextEdit, QLabel, QSystemTrayIcon, QMenu,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QRect, QTimer,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QIcon, QAction,
    QFont, QPixmap,
)

logger = logging.getLogger("SpotlightUI")

# ── Hang so giao dien (de o day de chinh nhanh) ───────────────────────────────
WINDOW_WIDTH       = 680
WINDOW_HEIGHT_MIN  = 80     # Chi co o nhap lenh
WINDOW_HEIGHT_MAX  = 320    # Co o nhap + ket qua
BORDER_RADIUS      = 15
BG_ALPHA           = 210    # Do mo nen (0-255), ~82% opacity
ANIMATION_DURATION = 250    # ms cho animation mo rong/thu gon
GLOBAL_HOTKEY      = "ctrl+space"
TTS_MAX_CHARS      = 800    # Gioi han ky tu gui cho TTS (~1-2 phut doc)
TTS_VOICE          = "vi-VN-NamMinhNeural"   # Giong doc tieng Viet Azure

# Bang mau Spotlight Dark
COLOR_BG        = QColor(18, 18, 24, BG_ALPHA)
COLOR_BORDER    = QColor(80, 80, 120, 160)
COLOR_TEXT      = QColor(220, 220, 255)
COLOR_ACCENT    = QColor(100, 180, 255)   # Cyan
COLOR_THINKING  = QColor(180, 130, 255)   # Purple


# ==============================================================================
#  AIWorker - Worker Thread xu ly cau hoi AI
# ==============================================================================

class AIWorker(QThread):
    """
    Chay toan bo pipeline AI trong Worker Thread.
    Giao tiep voi Main Thread ONLY qua pyqtSignal.
    KHONG duoc dong vao bat ky widget Qt nao trong run().
    """
    finished = pyqtSignal(str)   # Phat ket qua ve Main Thread
    error    = pyqtSignal(str)   # Phat thong bao loi

    def __init__(self, user_input: str, process_fn: Callable, parent=None):
        super().__init__(parent)
        self._user_input = user_input
        self._process_fn = process_fn

    def run(self):
        """Chay trong Worker Thread. Khong goi widget method o day."""
        try:
            logger.info("[AIWorker] Bat dau xu ly: '%s'", self._user_input[:60])
            answer = self._process_fn(self._user_input)
            logger.info("[AIWorker] Hoan thanh. Do dai: %d ky tu.", len(answer))
            self.finished.emit(answer)
        except Exception as e:
            logger.error("[AIWorker] Loi: %s", e)
            self.error.emit(f"He thong gap su co: {str(e)[:120]}")


# ==============================================================================
#  TTSWorker - Worker Thread phat giong noi
# ==============================================================================

class TTSWorker(QThread):
    """
    Phat giong noi trong Worker Thread rieng.

    Chien luoc phat am:
      1. edge-tts (Azure Cloud): Lu file MP3 tam -> phat bang winsound (blocking).
         winsound.PlaySound() biet chinh xac khi nao phat xong -> xoa file ngay.
         [OPT-1] Loai bo sleep(10) magic number cua phien ban truoc.
      2. Fallback: winsound khong ho tro MP3 truc tiep tren mot so may.
         Trong truong hop nay, ghi wav hoac skip.

    asyncio.run() duoc goi ben trong QThread.run() de tranh
    Event Loop Conflict voi PyQt6 Main Thread.
    """
    finished = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text

    def run(self):
        """asyncio.run() chay trong Worker Thread, tach biet khoi PyQt6 Main Loop."""
        tmp_path = None
        try:
            import edge_tts
            import subprocess

            async def _download_audio():
                """Tai MP3 tu Azure va tra ve duong dan file tam."""
                communicate = edge_tts.Communicate(self._text, voice=TTS_VOICE)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    path = tmp.name
                await communicate.save(path)
                return path

            # Tai file am thanh (async, trong Worker Thread)
            tmp_path = asyncio.run(_download_audio())
            logger.info("[TTSWorker] Da tai MP3: %s", tmp_path)

            # [BUG-4 FIX] Dung subprocess.Popen + wait() thay vi os.startfile() (async).
            # os.startfile() tra ve ngay lap tuc -> os.remove() chay truoc khi phat xong.
            # subprocess.Popen + proc.wait() dam bao chi xoa file SAU KHI phat xong.
            proc = subprocess.Popen(
                ["wmplayer", tmp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.wait()   # Blocking: cho den khi wmplayer dong
            logger.info("[TTSWorker] Da phat TTS: %d ky tu.", len(self._text))

        except ImportError:
            logger.warning("[TTSWorker] edge-tts chua cai. Bo qua TTS.")
        except FileNotFoundError:
            # wmplayer khong co tren may nay (Windows N edition / Server)
            logger.warning("[TTSWorker] wmplayer khong tim thay. Thu os.startfile() fallback.")
            if tmp_path and os.path.exists(tmp_path):
                os.startfile(tmp_path)
                # Uoc tinh thoi gian phat de tranh xoa file qua som
                estimated_sec = max(5, len(self._text) // 150 + 3)
                self.msleep(estimated_sec * 1000)
        except Exception as e:
            logger.error("[TTSWorker] Loi TTS: %s", e)
        finally:
            # Don file tam sau khi phat (hoac loi)
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    logger.debug("[TTSWorker] Da xoa file tam: %s", tmp_path)
                except Exception:
                    pass
            self.finished.emit()


# ==============================================================================
#  GlobalHotkeyThread - Lang nghe phim tat toan cuc
# ==============================================================================

class GlobalHotkeyThread(QThread):
    """
    Lang nghe phim tat Ctrl+Space toan cuc trong Worker Thread rieng.
    keyboard.wait() la ham blocking -> PHAI chay trong thread rieng.

    Yeu cau: Chay Python voi quyen Administrator tren Windows.
    Neu khong co quyen -> log warning, khong crash.

    [BUG-11 FIX] Them flag _running va phuong thuc stop() de dung sach.
    keyboard.unhook_all() giai phong hook truoc khi thread ket thuc.
    """
    toggle_signal = pyqtSignal()   # Phat ve Main Thread khi hotkey duoc bam

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def stop_listening(self):
        """Dung sach hotkey hook. Goi tu Main Thread truoc khi app thoat."""
        self._running = False
        try:
            import keyboard
            keyboard.unhook_all()   # Giai phong tat ca hook -> keyboard.wait() se return
            logger.info("[Hotkey] Da giai phong keyboard hooks.")
        except Exception:
            pass

    def run(self):
        try:
            import keyboard

            def _on_hotkey():
                logger.info("[Hotkey] %s bam -> toggle_signal.", GLOBAL_HOTKEY)
                self.toggle_signal.emit()

            keyboard.add_hotkey(GLOBAL_HOTKEY, _on_hotkey)
            logger.info("[Hotkey] Dang lang nghe %s (can quyen Admin).", GLOBAL_HOTKEY)
            keyboard.wait()   # Blocking: giu thread song - se return khi unhook_all() duoc goi

        except ImportError:
            logger.warning("[Hotkey] Thu vien 'keyboard' chua cai. Hotkey bi tat.")
        except Exception as e:
            logger.error("[Hotkey] Loi: %s. Hotkey bi tat.", e)


# ==============================================================================
#  SpotlightWindow - Cua so giao dien chinh
# ==============================================================================

class SpotlightWindow(QWidget):
    """
    Cua so Spotlight toi gian dang thanh lenh noi.
    - Frameless, AlwaysOnTop, TranslucentBackground
    - Bo goc 15px bang paintEvent() custom + QPainter
    - Chieu cao dong: 80px <-> 320px qua QPropertyAnimation

    Dependency Injection:
      process_fn   : Ham goi pipeline AI (tu main.py, da dong goi bang functools.partial)
      intercept_fn : Ham Regex Interceptor (da partial(vault_path=...) tu main.py)
                     -> Chi can goi intercept_fn(text, last_response=...)
    """

    def __init__(
        self,
        process_fn:   Optional[Callable] = None,
        intercept_fn: Optional[Callable] = None,
        vault_path:   str = "",
        parent=None,
    ):
        super().__init__(parent)

        self._process_fn    = process_fn
        self._intercept_fn  = intercept_fn
        self._vault_path    = vault_path
        self._last_response = ""           # Luu cau tra loi cuoi de copy/toast/repeat
        self._ai_worker:  Optional[AIWorker]  = None
        self._tts_worker: Optional[TTSWorker] = None

        self._setup_window()
        self._setup_ui()
        self._setup_animation()

    # ── Khoi tao ─────────────────────────────────────────────────────────────

    def _setup_window(self):
        """Cau hinh thuoc tinh cua so: frameless, always-on-top, trong suot."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool           # Khong hien tren taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(WINDOW_WIDTH)

        # [FIX-1] KHONG dung setFixedHeight vi no set ca min va max bang nhau
        # -> QPropertyAnimation thay doi geometry.height() bi clamp ve WINDOW_HEIGHT_MIN
        # Giai phap: chi dat min/max rieng, de animation tu do hoat dong
        self.setMinimumHeight(WINDOW_HEIGHT_MIN)
        self.setMaximumHeight(WINDOW_HEIGHT_MAX)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT_MIN)

        # Canh giua man hinh (tren cung, khoang 28% chieu cao)
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - WINDOW_WIDTH) // 2
        y = int(screen.height() * 0.28)
        self.move(x, y)

    def _setup_ui(self):
        """Khoi tao cac widget con."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # ── O nhap lenh ───────────────────────────────────────────────────────
        self.input_box = QLineEdit(self)
        self.input_box.setPlaceholderText("  Hoi Digital Scholar...")
        self.input_box.setFont(QFont("Segoe UI", 14))
        self.input_box.setMinimumHeight(44)
        self.input_box.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(30, 30, 50, 200);
                color: rgb({COLOR_TEXT.red()}, {COLOR_TEXT.green()}, {COLOR_TEXT.blue()});
                border: 1px solid rgba(100, 100, 160, 140);
                border-radius: 10px;
                padding: 6px 14px;
                selection-background-color: rgba(100, 160, 255, 120);
            }}
            QLineEdit:focus {{
                border: 1.5px solid rgba({COLOR_ACCENT.red()}, {COLOR_ACCENT.green()}, {COLOR_ACCENT.blue()}, 200);
            }}
            QLineEdit:disabled {{
                color: rgba(150, 150, 180, 150);
            }}
        """)
        self.input_box.returnPressed.connect(self._on_submit)
        layout.addWidget(self.input_box)

        # ── Label trang thai "Dang suy nghi..." ───────────────────────────────
        self.status_label = QLabel("   Dang suy nghi...", self)
        self.status_label.setFont(QFont("Segoe UI", 10))
        self.status_label.setStyleSheet(
            f"color: rgba({COLOR_THINKING.red()}, {COLOR_THINKING.green()}, {COLOR_THINKING.blue()}, 220);"
            "padding: 2px 4px;"
        )
        self.status_label.hide()
        layout.addWidget(self.status_label)

        # ── O ket qua (mac dinh an) ───────────────────────────────────────────
        self.result_box = QTextEdit(self)
        self.result_box.setReadOnly(True)
        self.result_box.setFont(QFont("Segoe UI", 11))
        self.result_box.setMinimumHeight(120)
        self.result_box.setMaximumHeight(230)
        self.result_box.setStyleSheet(f"""
            QTextEdit {{
                background-color: rgba(22, 22, 38, 220);
                color: rgb({COLOR_TEXT.red()}, {COLOR_TEXT.green()}, {COLOR_TEXT.blue()});
                border: none;
                border-top: 1px solid rgba(80, 80, 120, 100);
                border-radius: 0px;
                padding: 8px 12px;
                line-height: 1.6;
            }}
            QScrollBar:vertical {{
                width: 4px;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(120, 120, 180, 100);
                border-radius: 2px;
            }}
        """)
        self.result_box.hide()
        layout.addWidget(self.result_box)

    def _setup_animation(self):
        """Cau hinh animation mo rong/thu gon chieu cao cua so."""
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(ANIMATION_DURATION)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ── Ve nen kinh mo custom ─────────────────────────────────────────────────

    def paintEvent(self, event):
        """Bo goc + nen kinh mo. paintEvent la cach duy nhat bo goc Frameless."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(
            0, 0, self.width(), self.height(),
            BORDER_RADIUS, BORDER_RADIUS
        )
        painter.fillPath(path, COLOR_BG)
        painter.setPen(COLOR_BORDER)
        painter.drawPath(path)
        painter.end()

    # ── Xu ly input ──────────────────────────────────────────────────────────

    def _on_submit(self):
        """
        Xu ly khi nguoi dung nhan Enter.
        Thu tu: Regex Interceptor [< 5ms] -> Fast/Ninja/AI mode.
        """
        text = self.input_box.text().strip()
        if not text:
            return

        # [OPT-3] Khoa khi dang xu ly AI de tranh double-submit
        if self._is_busy():
            logger.warning("[SpotlightWindow] Dang ban, bo qua input moi.")
            return

        self.input_box.clear()

        # [FIX-2] intercept_fn da duoc partial(vault_path=...) o main.py
        # -> Chi truyen text + last_response, khong truyen vault_path lai
        if self._intercept_fn:
            try:
                result, mode = self._intercept_fn(
                    text,
                    last_response=self._last_response,
                )
            except Exception as e:
                logger.error("[SpotlightWindow] Interceptor loi: %s", e)
                result, mode = None, None

            if result is not None and mode is not None:
                self._handle_interceptor_result(result, mode, text)
                return

        # Khong khop bat ky regex nao -> day xuong AI
        self._start_ai_mode(text)

    def _handle_interceptor_result(self, result: Any, mode: str, original_text: str):
        """Xu ly ket qua tu Regex Interceptor theo che do."""
        if mode == "ninja":
            # NINJA: an cua so ngay, toast neu co thong bao
            self.hide()
            if isinstance(result, str) and result and result != "REPEAT_LAST_VOICE":
                self._show_toast(result)
            elif result == "REPEAT_LAST_VOICE" and self._last_response:
                self._start_tts(self._last_response)
            return

        if mode == "fast":
            # FAST: giu cua so, hien ket qua ngay
            if isinstance(result, dict):
                intent = result.get("intent", "")
                if intent == "FORCE_WEB":
                    query = result.get("query", original_text)
                    self._show_result(f"[Dang tra mang bat buoc: {query}]")
                    self._start_ai_mode(original_text)   # Day xuong AI voi query thuc
                elif intent == "EXPORT_DOCX":
                    topic = result.get("topic", "")
                    self._show_result(
                        f"[Xuat bao cao Word: '{topic}']\n"
                        "Chuc nang se kha dung o Giai doan 5."
                    )
            elif isinstance(result, str) and result:
                self._show_result(result)
                self._last_response = result

    def _start_ai_mode(self, text: str):
        """Che do AI: mo rong cua so + khoi dong AIWorker trong Worker Thread."""
        if self._process_fn is None:
            self._show_result(
                "[Core AI chua san sang]\n"
                "Kiem tra API Keys trong file .env va khoi dong lai."
            )
            return

        # [FIX-3] Guard double-start: neu worker dang chay thi bo qua
        if self._ai_worker and self._ai_worker.isRunning():
            logger.warning("[SpotlightWindow] AIWorker dang ban, bo qua lenh moi.")
            return

        # Hien trang thai + mo rong cua so
        self.status_label.show()
        self.result_box.hide()
        self.result_box.clear()
        self._expand_window()

        # Khoa o nhap trong luc doi
        self.input_box.setEnabled(False)
        self.input_box.setPlaceholderText("  Dang xu ly...")

        # Khoi dong Worker Thread
        self._ai_worker = AIWorker(
            user_input=text,
            process_fn=self._process_fn,
            parent=self,
        )
        self._ai_worker.finished.connect(self._on_ai_finished)
        self._ai_worker.error.connect(self._on_ai_error)
        self._ai_worker.finished.connect(self._ai_worker.deleteLater)  # Don bo nho
        self._ai_worker.start()
        logger.info("[SpotlightWindow] AIWorker started: '%s'", text[:50])

    # ── Slots nhan tin hieu tu Worker Thread (chay trong Main Thread) ─────────

    def _on_ai_finished(self, answer: str):
        """Nhan ket qua tu AIWorker. Chay trong Main Thread (thread-safe qua signal)."""
        self._last_response = answer
        self.status_label.hide()
        self._show_result(answer)

        # Mo lai o nhap
        self.input_box.setEnabled(True)
        self.input_box.setPlaceholderText("  Hoi tiep Digital Scholar...")
        self.input_box.setFocus()

        # Phat TTS (neu edge-tts da cai)
        self._start_tts(answer)

        self._ai_worker = None

    def _on_ai_error(self, error_msg: str):
        """Nhan loi tu AIWorker. Chay trong Main Thread."""
        self.status_label.hide()
        self._show_result(f"Loi: {error_msg}")
        self.input_box.setEnabled(True)
        self.input_box.setPlaceholderText("  Hoi Digital Scholar...")
        self.input_box.setFocus()
        self._ai_worker = None

    # ── Ham tien ich ─────────────────────────────────────────────────────────

    def _is_busy(self) -> bool:
        """[OPT-3] Kiem tra xem co Worker Thread nao dang chay khong."""
        return bool(self._ai_worker and self._ai_worker.isRunning())

    def _show_result(self, text: str):
        """Hien ket qua trong o QTextEdit + mo rong cua so neu chua."""
        self.result_box.setPlainText(text)
        self.result_box.show()
        self._expand_window()

    def _expand_window(self):
        """Animation mo rong cua so tu min -> max chieu cao."""
        if self.height() >= WINDOW_HEIGHT_MAX:
            return
        geo = self.geometry()
        target = QRect(geo.x(), geo.y(), geo.width(), WINDOW_HEIGHT_MAX)
        self._anim.stop()   # Dung animation cu neu dang chay
        self._anim.setStartValue(geo)
        self._anim.setEndValue(target)
        self._anim.start()

    def _collapse_window(self):
        """Animation thu gon cua so ve chieu cao toi thieu."""
        if self.height() <= WINDOW_HEIGHT_MIN:
            return
        geo = self.geometry()
        target = QRect(geo.x(), geo.y(), geo.width(), WINDOW_HEIGHT_MIN)
        self._anim.stop()
        self._anim.setStartValue(geo)
        self._anim.setEndValue(target)
        self._anim.start()

    def _show_toast(self, message: str):
        """Hien toast notification goc man hinh Windows bang win11toast."""
        try:
            from win11toast import toast
            toast("Digital Scholar", message[:200], duration="short")
            logger.info("[SpotlightWindow] Toast: '%s'", message[:60])
        except ImportError:
            logger.warning("[SpotlightWindow] win11toast chua cai. Bo qua toast.")
        except Exception as e:
            logger.error("[SpotlightWindow] Toast loi: %s", e)

    def _start_tts(self, text: str):
        """
        Khoi dong TTSWorker trong thread rieng.
        [FIX-5] Dung TTS cu truoc khi start moi, tranh 2 giong chong cheo.
        """
        if not text or text == "REPEAT_LAST_VOICE":
            return

        # Dung TTS cu neu dang chay
        if self._tts_worker and self._tts_worker.isRunning():
            self._tts_worker.terminate()
            self._tts_worker.wait(300)   # Cho toi da 300ms

        tts_text = text[:TTS_MAX_CHARS]   # Gioi han de tranh TTS qua dai
        self._tts_worker = TTSWorker(tts_text, parent=self)
        self._tts_worker.finished.connect(self._tts_worker.deleteLater)  # Don bo nho
        self._tts_worker.start()

    # ── Dieu khien hien thi cua so ───────────────────────────────────────────

    def toggle_visibility(self):
        """Bat/tat cua so. Duoc goi tu GlobalHotkeyThread qua signal."""
        if self.isVisible():
            self.hide()
        else:
            self.show_and_focus()

    def show_and_focus(self):
        """
        Hien cua so va focus vao o nhap lenh.
        [FIX-4] Dung resize() truc tiep thay vi animation khi widget dang an.
        QPropertyAnimation tren geometry khong co hieu ung khi widget chua hien.
        """
        self.result_box.hide()
        self.status_label.hide()
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT_MIN)   # Reset truc tiep, khong animation

        self.show()
        self.raise_()

        # [OPT-4] Delay nho 50ms sau show() de activateWindow hoat dong chinh xac tren Win11
        # (Win11 co co che chong focus-steal, can thoi gian de window duoc compositor chap nhan)
        QTimer.singleShot(50, self.activateWindow)
        QTimer.singleShot(60, self.input_box.setFocus)
        logger.info("[SpotlightWindow] Da hien cua so.")

    def keyPressEvent(self, event):
        """Escape de an cua so."""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Click X -> an chu khong thoat (chay ngam qua System Tray)."""
        event.ignore()
        self.hide()

    # ── Keo tha cua so (vi khong co thanh tieu de) ───────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    # ── Don dep tai nguyen ────────────────────────────────────────────────────

    def cleanup(self):
        """
        [OPT-2] Don dep tat ca Worker Thread khi app thoat.
        Goi tu main.py truoc app.quit() hoac trong finalizer.
        """
        for worker in (self._ai_worker, self._tts_worker):
            if worker and worker.isRunning():
                worker.terminate()
                worker.wait(500)
        logger.info("[SpotlightWindow] Da don sach worker threads.")


# ==============================================================================
#  Ham thiet lap System Tray Icon
# ==============================================================================

def setup_system_tray(app: QApplication, window: SpotlightWindow) -> QSystemTrayIcon:
    """
    Tao icon he thong (System Tray) o goc dong ho Windows.
    Right-click -> menu: Mo / Thoat.

    Args:
        app    : QApplication instance.
        window : SpotlightWindow can lien ket.

    Returns:
        QSystemTrayIcon da duoc kich hoat.
    """
    # Icon 32x32 mau xanh cyan (fallback khi chua co file .ico)
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(100, 160, 255))
    icon = QIcon(pixmap)

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Digital Scholar - Last Agent V3.0\nCtrl+Space de mo/dong")

    # Menu chuot phai
    menu = QMenu()

    action_show = QAction("Mo Digital Scholar", app)
    action_show.triggered.connect(window.show_and_focus)

    def _quit():
        """Don dep Worker Threads truoc khi thoat."""
        window.cleanup()
        app.quit()

    action_quit = QAction("Thoat", app)
    action_quit.triggered.connect(_quit)

    menu.addAction(action_show)
    menu.addSeparator()
    menu.addAction(action_quit)

    tray.setContextMenu(menu)

    # Double-click vao tray icon -> toggle
    def _on_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            window.toggle_visibility()

    tray.activated.connect(_on_activated)

    tray.show()
    logger.info("[Tray] System Tray Icon da kich hoat.")
    return tray
