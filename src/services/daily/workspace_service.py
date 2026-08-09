import os
import json
import logging
from datetime import datetime, timedelta
import google.genai as genai
from pydantic import BaseModel, Field

from googleapiclient.discovery import build
from src.services.daily.google_auth import get_google_credentials
from src.shared.config import GEMINI_API_KEY

logger = logging.getLogger("WorkspaceService")

# ══════════════════════════════════════════════════════════════════════════════
# LLM CHEAP GATING FOR CALENDAR EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

class CalendarEventSchema(BaseModel):
    title: str = Field(description="Tiêu đề sự kiện")
    date_iso: str = Field(description="Ngày diễn ra sự kiện theo định dạng YYYY-MM-DD. Nếu không rõ, hãy để trống.")
    time_iso: str = Field(description="Giờ diễn ra sự kiện theo định dạng HH:MM:SS. Nếu không rõ, hãy để trống.")
    duration_minutes: int = Field(default=60, description="Thời lượng dự kiến tính bằng phút. Mặc định là 60.")

def _extract_event_info(user_text: str) -> CalendarEventSchema:
    """Sử dụng LLM siêu nhanh để ép kiểu dữ liệu từ natural language sang JSON."""
    if not GEMINI_API_KEY or "điền" in GEMINI_API_KEY.lower():
        raise ValueError("Chưa cấu hình GEMINI_API_KEY.")
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    now = datetime.now()
    
    prompt = f"""
    Bạn là một máy phân tích dữ liệu tĩnh (parser).
    Hôm nay là: {now.strftime('%Y-%m-%d %H:%M:%S')} (Thứ {now.weekday() + 2})
    Nhiệm vụ: Trích xuất thông tin tạo lịch từ văn bản của người dùng.
    Quy tắc TỐI QUAN TRỌNG:
    - KHÔNG được tự bịa ra ngày hoặc giờ nếu người dùng không nhắc đến.
    - Nếu người dùng nói "chiều mai lúc 3h", hãy tính toán ra date_iso và time_iso chính xác.
    
    Văn bản: "{user_text}"
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CalendarEventSchema,
            temperature=0.0
        ),
    )
    
    try:
        data = json.loads(response.text)
        return CalendarEventSchema(**data)
    except Exception as e:
        logger.error(f"[WorkspaceService] Lỗi parse JSON từ LLM: {e}")
        return CalendarEventSchema(title=user_text, date_iso="", time_iso="")

# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE CALENDAR ACTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _get_calendar_service():
    creds = get_google_credentials()
    return build('calendar', 'v3', credentials=creds)

def get_calendar_events(user_text: str = "") -> str:
    """Đọc sự kiện lịch (Mặc định là các sự kiện sắp tới trong hôm nay/ngày mai)."""
    try:
        service = _get_calendar_service()
        # Mặc định lấy từ thời điểm hiện tại đến 3 ngày tới
        now = datetime.utcnow().isoformat() + 'Z'  
        events_result = service.events().list(
            calendarId='primary', timeMin=now,
            maxResults=5, singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        if not events:
            return "Bạn không có lịch trình nào sắp tới."
            
        result = "Lịch trình sắp tới của bạn:\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            # Format lại giờ cho dễ đọc
            try:
                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                time_str = dt.strftime("%d/%m lúc %H:%M")
            except ValueError:
                time_str = start
            result += f"- {time_str}: {event['summary']}\n"
            
        return result
    except Exception as e:
        logger.error(f"[WorkspaceService] Lỗi Calendar API: {e}")
        return f"Không thể lấy lịch: {e}"

def create_calendar_event(user_text: str) -> str:
    """
    Sử dụng LLM Cheap Gating để trích xuất, 
    nếu thiếu thông tin thì báo lỗi bắt user nhập lại,
    nếu đủ thì gọi Google API, gắn cờ báo thức 30p.
    """
    try:
        # Bước 1: LLM Parsing
        parsed = _extract_event_info(user_text)
        
        # Bước 2: Validation (Không cho phép ảo giác ngày giờ)
        if not parsed.date_iso or not parsed.time_iso:
            return f"Tôi hiểu bạn muốn tạo lịch '{parsed.title}'. Nhưng bạn chưa cung cấp ngày hoặc giờ cụ thể. Hãy nói lại chi tiết hơn nhé!"
            
        # Tính toán start_time và end_time
        start_time_str = f"{parsed.date_iso}T{parsed.time_iso}"
        start_dt = datetime.fromisoformat(start_time_str)
        end_dt = start_dt + timedelta(minutes=parsed.duration_minutes)
        
        # Bước 3: Tạo payload
        event_body = {
            'summary': parsed.title,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': 'Asia/Ho_Chi_Minh',
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': 'Asia/Ho_Chi_Minh',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 30},
                ],
            },
        }
        
        # Bước 4: Gọi API
        service = _get_calendar_service()
        event = service.events().insert(calendarId='primary', body=event_body).execute()
        
        link = event.get('htmlLink', '')
        return f"Đã tạo lịch '{parsed.title}' vào lúc {parsed.time_iso} ngày {parsed.date_iso}. Điện thoại của bạn sẽ đổ chuông nhắc trước 30 phút."
        
    except Exception as e:
        logger.error(f"[WorkspaceService] Lỗi tạo lịch: {e}")
        return f"Lỗi tạo sự kiện: {e}"
