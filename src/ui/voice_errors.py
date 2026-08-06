"""
voice_errors.py - Unified Error Model cho Voice Pipeline
=========================================================
Phan cap loi giup:
  - Caller biet duoc loi co the retry hay khong
  - Log / UI hien thi dung message
  - Khong doi catch Exception blanket

Hierarchy:
  VoiceError
    VoiceTimeoutError      -- retry duoc (network timeout, asyncio.TimeoutError)
    VoiceNetworkError      -- retry duoc (connection reset, socket error)
    VoiceCancelledError    -- KHONG retry (user huy)
    VoicePermissionError   -- KHONG retry (401/403, wrong API key)
    VoiceInvalidAudioError -- KHONG retry (audio qua ngan, dinh dang sai)
"""


class VoiceError(Exception):
    """Base exception cho toan bo voice pipeline."""


class VoiceTimeoutError(VoiceError):
    """Request Gemini qua 15s khong co phan hoi. Co the retry."""


class VoiceNetworkError(VoiceError):
    """Loi mang tam thoi (connection reset, socket timeout). Co the retry."""


class VoiceCancelledError(VoiceError):
    """User huy request (nhan ESC). Khong retry."""


class VoicePermissionError(VoiceError):
    """Loi quyen truy cap (401/403, API key sai). Khong retry — can fix config."""


class VoiceInvalidAudioError(VoiceError):
    """Audio qua ngan, khong co giong noi, hoac dinh dang sai. Khong retry."""
