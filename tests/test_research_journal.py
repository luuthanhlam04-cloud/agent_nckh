"""
tests/test_research_journal.py
Unit tests for ResearchJournalService.
"""

import os
import shutil
import tempfile
import unittest
from src.services.research_journal import ResearchJournalService


class TestResearchJournal(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.journal_service = ResearchJournalService(vault_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_record_gap_and_read(self):
        file_path = self.journal_service.record_gap(
            paper_title="GraphRAG Scalability Study",
            hypothesis_or_gap="Dynamic edge updates cause linear re-embedding overhead",
            bottleneck="Memory thrashing on graphs with > 1M edges",
            source_tags=["GraphRAG", "Benchmark"]
        )
        self.assertTrue(os.path.exists(file_path))
        content = self.journal_service.read_today_journal()
        self.assertIn("GraphRAG Scalability Study", content)
        self.assertIn("Dynamic edge updates", content)
        self.assertIn("#GraphRAG", content)

    def test_socratic_prompt_generation(self):
        prompt = ResearchJournalService.generate_socratic_prompt("Knowledge Graphs")
        self.assertIn("Gợi ý phản biện học thuật", prompt)
        self.assertIn("giả định ngầm", prompt)


if __name__ == "__main__":
    unittest.main()

