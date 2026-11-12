"""
tests/test_intent_sniffer.py
Unit tests for HybridIntentSniffer and VietnameseStopwordStripper.
"""

import unittest
from src.core.intent_sniffer import HybridIntentSniffer


class TestHybridIntentSniffer(unittest.TestCase):
    def setUp(self):
        self.sniffer = HybridIntentSniffer()

    def test_youtube_clean_slot(self):
        # Văn nói lộn xộn với từ đệm, xưng hô
        query = "Ờ... mở giùm tao cái... bài gì của Sơn Tùng ấy trên YouTube đi"
        res = self.sniffer.sniff(query)
        self.assertTrue(res.is_intercepted)
        self.assertEqual(res.intent, "OS_YOUTUBE")
        self.assertEqual(res.action_type, "youtube_search")
        self.assertIn("Sơn Tùng", res.cleaned_slot)
        # Kiểm tra không bị dính từ rác
        self.assertNotIn("giùm", res.cleaned_slot.lower())
        self.assertNotIn("tao", res.cleaned_slot.lower())
        self.assertNotIn("youtube", res.cleaned_slot.lower())
        self.assertFalse(res.needs_clarification)

    def test_youtube_home_page(self):
        # Lệnh mở youtube chung -> mở trang chủ youtube
        query = "Ê mở youtube đi"
        res = self.sniffer.sniff(query)
        self.assertTrue(res.is_intercepted)
        self.assertEqual(res.intent, "OS_YOUTUBE")
        self.assertEqual(res.action_type, "youtube_home")

    def test_youtube_clarification_on_empty_slot(self):
        # Lệnh yêu cầu phát nhạc nhưng không rõ tên bài
        query = "Ê phát bài hát coi"
        res = self.sniffer.sniff(query)
        self.assertTrue(res.is_intercepted)
        self.assertTrue(res.needs_clarification)
        self.assertIsNotNone(res.clarification_prompt)

    def test_volume_controls(self):
        res1 = self.sniffer.sniff("Tắt tiếng giùm tao với")
        self.assertTrue(res1.is_intercepted)
        self.assertEqual(res1.intent, "OS_VOLUME")
        self.assertEqual(res1.action_type, "volume_mute")

        res2 = self.sniffer.sniff("Chỉnh âm lượng 65% nhé")
        self.assertTrue(res2.is_intercepted)
        self.assertEqual(res2.intent, "OS_VOLUME")
        self.assertEqual(res2.action_type, "volume_set")
        self.assertEqual(res2.metadata["level"], 65)

    def test_passthrough_to_rag(self):
        # Câu hỏi nghiên cứu khoa học -> Không bị chặn
        query = "Cho tôi biết các giả định cốt lõi của GraphRAG trong môi trường dynamic graph"
        res = self.sniffer.sniff(query)
        self.assertFalse(res.is_intercepted)


if __name__ == "__main__":
    unittest.main()
