"""
tests/test_silero_vad.py
Unit tests for SileroVAD detector.
"""

import unittest
import numpy as np
from src.ui.silero_vad import SileroVAD


class TestSileroVAD(unittest.TestCase):
    def setUp(self):
        self.vad = SileroVAD(sample_rate=16000, threshold=0.5)

    def test_silero_vad_initialization(self):
        self.assertTrue(self.vad.is_ready(), "Silero VAD should be ready using local onnx asset")

    def test_silence_detection(self):
        # 1600 samples of pure silence (100ms at 16kHz)
        silence_int16 = np.zeros(1600, dtype=np.int16).tobytes()
        prob = self.vad.get_speech_probability(silence_int16)
        self.assertLess(prob, 0.3, f"Silence prob should be low, got {prob}")
        self.assertFalse(self.vad.is_speech(silence_int16))

    def test_reset(self):
        self.vad.reset()
        self.assertEqual(len(self.vad._buffer), 0)


if __name__ == "__main__":
    unittest.main()

