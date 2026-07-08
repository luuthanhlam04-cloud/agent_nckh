import asyncio
import time
import threading
from pathlib import Path
from src.utils.watchdog_listener import InboxEventHandler
from src.ui.voice_engine import WhisperSTT
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestAudit")

async def test_watchdog_debounce():
    logger.info("=== TEST 1: WATCHDOG DEBOUNCE ===")
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    
    handler = InboxEventHandler(queue, loop)
    
    class FakeEvent:
        def __init__(self, path):
            self.src_path = path
            self.is_directory = False
            
    # Giả lập bấm Ctrl+S 5 lần trong 1 giây cho cùng 1 file
    fake_path = "C:/fake/01_Inbox/test_doc.pdf"
    
    for i in range(5):
        logger.info(f"Giả lập lưu file lần {i+1}...")
        handler.on_modified(FakeEvent(fake_path))
        await asyncio.sleep(0.1)
        
    await asyncio.sleep(1)
    
    # Kiểm tra số lượng item trong queue (kỳ vọng: 1)
    qsize = queue.qsize()
    logger.info(f"Số sự kiện được đẩy vào Queue xử lý: {qsize} (Kỳ vọng: 1)")
    if qsize == 1:
        logger.info("✅ Watchdog Debounce hoạt động hoàn hảo!")
    else:
        logger.error("❌ Watchdog Debounce THẤT BẠI!")

def test_whisper_singleton():
    logger.info("\n=== TEST 2: WHISPER STT SINGLETON ===")
    start_time = time.time()
    logger.info("Lần gọi 1 (Khởi tạo ban đầu)...")
    stt1 = WhisperSTT(model_name="tiny")
    logger.info(f"Thời gian nạp lần 1: {time.time() - start_time:.2f}s")
    
    start_time = time.time()
    logger.info("Lần gọi 2 (Singleton)...")
    stt2 = WhisperSTT(model_name="tiny")
    logger.info(f"Thời gian nạp lần 2: {time.time() - start_time:.4f}s")
    
    if stt1 is stt2:
        logger.info("✅ WhisperSTT Singleton hoạt động hoàn hảo (Zero-cost instantiation)!")
    else:
        logger.error("❌ WhisperSTT không phải Singleton!")

async def main():
    await test_watchdog_debounce()
    test_whisper_singleton()

if __name__ == "__main__":
    asyncio.run(main())
