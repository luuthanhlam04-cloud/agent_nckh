# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QCoreApplication
import os

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
    tray.setToolTip("Digital Scholar - Agent V4.0\nCtrl+Space de mo/dong")

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
        try:
            from PyQt6.QtWidgets import QSystemTrayIcon
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                window.toggle_visibility()
        except Exception as e:
            logger.debug("[Tray] Loi xu ly tray activation: %s", e)

    tray.activated.connect(_on_activated)

    tray.show()
    logger.info("[Tray] System Tray Icon da kich hoat.")
    return tray
