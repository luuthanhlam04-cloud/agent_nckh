import os
import re
import urllib.parse
import subprocess
from datetime import datetime

# Windows API for volume control
import ctypes

def _sanitize_command(cmd: str) -> str:
    """Loại bỏ ký tự đặc biệt nguy hiểm để chống Command Injection."""
    return re.sub(r'[^a-zA-Z0-9\s-]', '', cmd).strip()

def get_current_time() -> str:
    now = datetime.now()
    weekday = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"][now.weekday()]
    return f"Hôm nay là {weekday}, ngày {now.strftime('%d/%m/%Y')}. Bây giờ là {now.strftime('%H:%M')} phút."

def open_website(domain: str) -> str:
    # Sử dụng DuckDuckGo "I'm Feeling Lucky" (!ducky) để tự động chuyển hướng đến trang đích
    ducky_url = f"https://duckduckgo.com/?q=!ducky+{urllib.parse.quote(domain)}"
    os.startfile(ducky_url)
    return f"Đã mở trang web: {domain}"

def open_application(app_name: str) -> str:
    safe_app = _sanitize_command(app_name)
    if safe_app:
        subprocess.Popen(f"start {safe_app}", shell=True)
        return f"Đã gửi lệnh khởi chạy ứng dụng: {safe_app}"
    return "Tên ứng dụng không hợp lệ."

def system_volume(action: str) -> str:
    """
    Sử dụng ctypes.windll.user32.keybd_event để giả lập phím tắt Windows:
    VK_VOLUME_MUTE = 0xAD (173)
    VK_VOLUME_DOWN = 0xAE (174)
    VK_VOLUME_UP = 0xAF (175)
    """
    try:
        user32 = ctypes.windll.user32
        action_lower = action.lower()
        if "tắt" in action_lower or "mute" in action_lower:
            user32.keybd_event(0xAD, 0, 0, 0)
            user32.keybd_event(0xAD, 0, 2, 0)
            return "Đã tắt âm lượng hệ thống."
        elif "giảm" in action_lower or "xuống" in action_lower:
            # Bấm giảm nhiều lần để giảm rõ rệt
            for _ in range(5):
                user32.keybd_event(0xAE, 0, 0, 0)
                user32.keybd_event(0xAE, 0, 2, 0)
            return "Đã giảm âm lượng."
        elif "tăng" in action_lower or "lên" in action_lower or "to" in action_lower:
            # Bấm tăng nhiều lần
            for _ in range(5):
                user32.keybd_event(0xAF, 0, 0, 0)
                user32.keybd_event(0xAF, 0, 2, 0)
            return "Đã tăng âm lượng."
        else:
            return "Không rõ lệnh điều chỉnh âm lượng (dùng: tăng/giảm/tắt)."
    except Exception as e:
        return f"Lỗi khi điều chỉnh âm lượng: {e}"
