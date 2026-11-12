import urllib.parse
import webbrowser
import threading
import logging

logger = logging.getLogger("MediaService")

def search_youtube(query: str) -> str:
    """
    Sử dụng luồng phụ để không block UI. Cố gắng trích xuất video bằng yt-dlp,
    nếu thất bại thì mở thẳng trang search kết quả của YouTube.
    """
    def _worker():
        try:
            import yt_dlp
            ydl_opts = {
                'default_search': 'ytsearch',
                'noplaylist': True,
                'quiet': True,
                'extract_flat': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)
                if 'entries' in info and len(info['entries']) > 0:
                    vid = info['entries'][0]['id']
                    webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
                    return
        except ImportError:
            logger.info("[MediaService] yt-dlp chưa cài đặt. Fallback sang trình duyệt.")
        except Exception as e:
            logger.warning(f"[MediaService] Lỗi lấy video YouTube qua yt-dlp: {e}")
            
        # FALLBACK: Lách Zero-Dependency
        webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}")
        
    threading.Thread(target=_worker, daemon=True, name="YouTubeAutoPlay").start()
    return f"Đang tìm và phát trên Youtube: {query}"


def open_youtube_home() -> str:
    """Mở trang chủ YouTube trong luồng phụ."""
    threading.Thread(
        target=lambda: webbrowser.open("https://www.youtube.com"),
        daemon=True,
        name="YouTubeHome"
    ).start()
    return "Đã mở trang chủ YouTube."
