import os
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger("GoogleAuth")

# Yêu cầu quyền truy cập vào Calendar
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events'
]

def get_google_credentials() -> Credentials:
    """
    Lấy thông tin xác thực OAuth2 của Google.
    Sẽ mở trình duyệt yêu cầu người dùng đăng nhập ở lần chạy đầu tiên.
    """
    creds = None
    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "config")
    token_path = os.path.join(config_dir, "token.json")
    credentials_path = os.path.join(config_dir, "credentials.json")

    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            logger.warning(f"[GoogleAuth] Không thể đọc token.json: {e}")

    # Nếu token hỏng hoặc hết hạn, yêu cầu người dùng xác thực lại
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"[GoogleAuth] Refresh token thất bại: {e}. Yêu cầu xác thực lại.")
                creds = None
                
        if not creds:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(f"Không tìm thấy file {credentials_path}. Vui lòng tạo OAuth Client ID từ Google Cloud Console.")
                
            logger.info("[GoogleAuth] Bắt đầu luồng xác thực OAuth qua trình duyệt...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Lưu lại token cho lần sau
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
            
    return creds
