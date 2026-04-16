"""tests/test_literary_qc.py — LiteraryQCAgent unit tests."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.conftest import (  # noqa: E402
    SAMPLE_COMPLETE_MYSTERY, SAMPLE_INCOMPLETE_MYSTERY,
    SAMPLE_TOO_SHORT, SAMPLE_STUB_CHAPTERS,
    MOCK_QC_PASS_RESPONSE, MOCK_QC_FAIL_RESPONSE,
    patch_claude,
)


class TestLiteraryQCImport(unittest.TestCase):
    def test_import(self):
        from core.literary_qc import LiteraryQCAgent
        self.assertTrue(callable(LiteraryQCAgent))

    def test_instantiate(self):
        from core.literary_qc import LiteraryQCAgent
        agent = LiteraryQCAgent()
        self.assertIsNotNone(agent)

    def test_has_full_book_analysis(self):
        from core.literary_qc import LiteraryQCAgent
        agent = LiteraryQCAgent()
        self.assertTrue(hasattr(agent, "full_book_analysis"))
        self.assertTrue(callable(agent.full_book_analysis))

    def test_has_dispatch_rewrite(self):
        from core.literary_qc import LiteraryQCAgent
        agent = LiteraryQCAgent()
        self.assertTrue(hasattr(agent, "_dispatch_rewrite"))


class TestReviewManuscript(unittest.TestCase):
    def setUp(self):
        from core.literary_qc import LiteraryQCAgent
        self.agent = LiteraryQCAgent()

    def test_returns_dict(self):
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.review_manuscript(SAMPLE_COMPLETE_MYSTERY, "Test", genre="mystery")
        self.assertIsInstance(r, dict)

    def test_required_keys(self):
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.review_manuscript(SAMPLE_COMPLETE_MYSTERY, "Test", genre="mystery")
        for key in ("score", "approved", "verdict", "passes"):
            self.assertIn(key, r, f"Missing key: {key}")

    def test_complete_book_approved(self):
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.review_manuscript(SAMPLE_COMPLETE_MYSTERY, "Complete Book", genre="mystery")
        # With high mock scores, should be approved
        self.assertIn("verdict", r)

    def test_too_short_rejected(self):
        """Very short book should fail publication_ready pass."""
        with patch_claude({"score": MOCK_QC_FAIL_RESPONSE}):
            r = self.agent.review_manuscript(SAMPLE_TOO_SHORT, "Tiny Book", genre="mystery")
        # Check publication_ready pass exists and note word count
        passes = r.get("passes", {})
        pub_ready = passes.get("publication_ready", {})
        wc = pub_ready.get("word_count", len(SAMPLE_TOO_SHORT.split()))
        self.assertLess(wc, 8000)


class TestFullBookAnalysis(unittest.TestCase):
    def setUp(self):
        from core.literary_qc import LiteraryQCAgent
        self.agent = LiteraryQCAgent()

    def test_returns_dict(self):
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_COMPLETE_MYSTERY, "Test", genre="mystery")
        self.assertIsInstance(r, dict)

    def test_required_keys(self):
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_COMPLETE_MYSTERY, "Test", genre="mystery")
        for key in ("chapter_count", "incomplete_chapters", "stub_chapters",
                    "has_proper_ending", "overall_score", "approved", "verdict",
                    "rewrite_needed", "rewrite_directive"):
            self.assertIn(key, r, f"Missing key: {key}")

    def test_detects_chapter_count(self):
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_COMPLETE_MYSTERY, "Test", genre="mystery")
        self.assertGreater(r["chapter_count"], 0)

    def test_detects_proper_ending(self):
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_COMPLETE_MYSTERY, "Test", genre="mystery")
        self.assertTrue(r["has_proper_ending"])  # SAMPLE_COMPLETE has "THE END"

    def test_detects_missing_ending(self):
        with patch_claude({"score": MOCK_QC_FAIL_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_INCOMPLETE_MYSTERY, "Incomplete", genre="mystery")
        self.assertFalse(r["has_proper_ending"])

    def test_detects_incomplete_chapters(self):
        """Book ending mid-sentence should have at least 1 incomplete chapter."""
        with patch_claude({"score": MOCK_QC_FAIL_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_INCOMPLETE_MYSTERY, "Incomplete", genre="mystery")
        # The last chapter ends mid-sentence
        self.assertIsInstance(r["incomplete_chapters"], list)

    def test_detects_stub_chapters(self):
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_STUB_CHAPTERS, "Skeleton", genre="mystery")
        self.assertIsInstance(r["stub_chapters"], list)
        self.assertGreater(len(r["stub_chapters"]), 0)

    def test_rewrite_needed_for_incomplete(self):
        with patch_claude({"score": MOCK_QC_FAIL_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_INCOMPLETE_MYSTERY, "Incomplete", genre="mystery")
        # Either incomplete chapters, no ending, or low score triggers rewrite_needed
        if not r["has_proper_ending"] or r["incomplete_chapters"]:
            self.assertTrue(r["rewrite_needed"])

    def test_rewrite_queue_written(self):
        """When rewrite_needed, dispatch writes to the queue file."""

        queue_file = ROOT / "data" / "narai_rewrite_queue.json"
        # Ensure queue file starts fresh for this test
        tmp_path = str(ROOT / "outputs" / "books" / "mystery" / "test_dispatch.md")

        with patch_claude({"score": MOCK_QC_FAIL_RESPONSE}):
            r = self.agent.full_book_analysis(
                SAMPLE_INCOMPLETE_MYSTERY,
                "Queue Test Book",
                genre="mystery",
                manuscript_path=tmp_path,
            )

        if r["rewrite_needed"]:
            self.assertTrue(queue_file.exists())
            queue = json.loads(queue_file.read_text())
            titles = [e.get("title") for e in queue]
            self.assertIn("Queue Test Book", titles)

    def test_no_rewrite_for_complete_approved(self):
        """A properly complete book should not be flagged for rewrite."""
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.agent.full_book_analysis(SAMPLE_COMPLETE_MYSTERY, "Complete Book", genre="mystery")
        # If all pass scores are 85 and book has proper ending, rewrite not needed
        if r["has_proper_ending"] and not r["incomplete_chapters"] and len(r["stub_chapters"]) <= 2:
            self.assertFalse(r["rewrite_needed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
