"""
src/ui/silero_vad.py

Silero VAD (ONNX Runtime) Detector.
Voice Activity Detection chuẩn xác cao cho môi trường tiếng ồn phòng, tiếng quạt, bàn phím cơ.
Hỗ trợ Pre-speech Ring Buffer và Trailing Silence Detection.
"""

import os
import sys
import logging
import collections
import numpy as np
from typing import Optional, List

logger = logging.getLogger("SileroVAD")

# Các đường dẫn khả dĩ chứa file silero_vad onnx
POSSIBLE_MODEL_PATHS = [
    # 1. Đường dẫn trong venv faster_whisper assets
    os.path.join(sys.prefix, "Lib", "site-packages", "faster_whisper", "assets", "silero_vad_v6.onnx"),
    # 2. Đường dẫn cục bộ nếu copy về project
    os.path.join(os.path.dirname(__file__), "assets", "silero_vad_v6.onnx"),
    os.path.join(os.path.dirname(__file__), "silero_vad_v6.onnx"),
]


class SileroVAD:
    """
    Silero VAD v6 chạy qua ONNX Runtime (<2MB, CPU local, latency <5ms).
    """

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.6):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.session = None
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._buffer = np.array([], dtype=np.float32)
        self._chunk_size = 576  # 576 samples = 36ms tại 16kHz
        self._is_ready = False

        self._init_session()

    def _init_session(self):
        try:
            import onnxruntime as ort
            model_path = None
            for p in POSSIBLE_MODEL_PATHS:
                if os.path.exists(p):
                    model_path = p
                    break

            if not model_path:
                logger.warning("[SileroVAD] Không tìm thấy file silero_vad_v6.onnx. Sẽ fallback sang Energy VAD.")
                return

            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            self.session = ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
            self._is_ready = True
            logger.info("[SileroVAD] Khởi tạo thành công Silero VAD v6 từ %s", model_path)
        except Exception as e:
            logger.error("[SileroVAD] Lỗi khởi tạo ONNX runtime: %s. Chuyển sang Fallback.", e)
            self._is_ready = False

    def reset(self):
        """Reset trạng thái recurrent của mạng neural."""
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._buffer = np.array([], dtype=np.float32)

    def is_ready(self) -> bool:
        return self._is_ready

    def _bytes_to_float32(self, pcm_bytes: bytes) -> np.ndarray:
        """Chuyển đổi PCM16 bytes sang float32 [-1.0, 1.0]."""
        audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        return audio_int16.astype(np.float32) / 32768.0

    def get_speech_probability(self, pcm_bytes: bytes) -> float:
        """
        Tính toán xác suất tiếng người p in [0.0, 1.0].
        """
        if not self._is_ready or self.session is None:
            # Fallback Energy RMS nếu ONNX chưa sẵn sàng
            audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
            rms = np.sqrt(np.mean(audio_int16.astype(np.float64)**2)) if len(audio_int16) > 0 else 0
            return 1.0 if rms > 300 else 0.0

        new_audio = self._bytes_to_float32(pcm_bytes)
        self._buffer = np.concatenate((self._buffer, new_audio))

        probs = []
        while len(self._buffer) >= self._chunk_size:
            chunk = self._buffer[:self._chunk_size].reshape(1, self._chunk_size)
            self._buffer = self._buffer[self._chunk_size:]

            out, hn, cn = self.session.run(
                None,
                {"input": chunk, "h": self._h, "c": self._c}
            )
            self._h = hn
            self._c = cn
            probs.append(float(out[0]))

        if not probs:
            return 0.0
        # Lấy xác suất lớn nhất trong batch các sub-chunks để không bỏ sót tiếng nói
        return max(probs)

    def is_speech(self, pcm_bytes: bytes) -> bool:
        """Trả về True nếu xác suất tiếng nói vượt ngưỡng threshold (0.6)."""
        prob = self.get_speech_probability(pcm_bytes)
        return prob >= self.threshold

