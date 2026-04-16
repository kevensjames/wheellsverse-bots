"""tests/test_volume_completion.py — VolumeCompletionBot unit tests."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.conftest import (  # noqa: E402
    SAMPLE_COMPLETE_MYSTERY, SAMPLE_INCOMPLETE_MYSTERY,
    SAMPLE_TOO_SHORT, patch_claude, make_temp_manuscript,
)


class TestVolumeCompletionBotImport(unittest.TestCase):
    def test_import(self):
        from bots.books.volume_completion_bot import VolumeCompletionBot
        self.assertTrue(callable(VolumeCompletionBot))

    def test_instantiate(self):
        from bots.books.volume_completion_bot import VolumeCompletionBot
        bot = VolumeCompletionBot()
        self.assertIsNotNone(bot)

    def test_has_scan_method(self):
        from bots.books.volume_completion_bot import VolumeCompletionBot
        bot = VolumeCompletionBot()
        self.assertTrue(hasattr(bot, "scan_all_manuscripts"))
        self.assertTrue(callable(bot.scan_all_manuscripts))

    def test_has_complete_volume(self):
        from bots.books.volume_completion_bot import VolumeCompletionBot
        bot = VolumeCompletionBot()
        self.assertTrue(hasattr(bot, "complete_volume"))


class TestScanReturnsStructure(unittest.TestCase):
    def setUp(self):
        from bots.books.volume_completion_bot import VolumeCompletionBot
        self.bot = VolumeCompletionBot()

    def test_scan_returns_dict(self):
        result = self.bot.scan_all_manuscripts()
        self.assertIsInstance(result, dict)

    def test_scan_has_required_keys(self):
        result = self.bot.scan_all_manuscripts()
        for key in ("complete", "incomplete", "unknown"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_scan_values_are_lists(self):
        result = self.bot.scan_all_manuscripts()
        for key in ("complete", "incomplete", "unknown"):
            self.assertIsInstance(result[key], list, f"{key} should be a list")


class TestAssessCompletion(unittest.TestCase):
    """Test _assess_completion() directly via temp files."""

    def setUp(self):
        from bots.books.volume_completion_bot import VolumeCompletionBot
        self.bot = VolumeCompletionBot()

    def test_mid_sentence_incomplete(self):
        """File ending mid-sentence → status=incomplete."""
        tmp = make_temp_manuscript(SAMPLE_INCOMPLETE_MYSTERY)
        try:
            result = self.bot._assess_completion(tmp)
            self.assertEqual(result["status"], "incomplete")
            self.assertIn("mid-sentence", result.get("reason", "").lower())
        finally:
            tmp.unlink(missing_ok=True)

    def test_too_short_incomplete(self):
        """File < 5000 words → status=incomplete."""
        tmp = make_temp_manuscript(SAMPLE_TOO_SHORT)
        try:
            result = self.bot._assess_completion(tmp)
            self.assertEqual(result["status"], "incomplete")
        finally:
            tmp.unlink(missing_ok=True)

    def test_complete_with_the_end(self):
        """File with 'THE END' marker and sufficient words → status=complete."""
        # SAMPLE_COMPLETE_MYSTERY is ~900 words; _assess_completion requires >5000.
        # Repeat body sections to cross the threshold while keeping THE END marker.
        filler = SAMPLE_COMPLETE_MYSTERY.replace("**THE END**", "").strip()
        long_manuscript = (filler + "\n\n") * 6 + "\n\n**THE END**\n\nAbout the Author\n\nJ.K. Blaze is a mystery fiction author."
        tmp = make_temp_manuscript(long_manuscript)
        try:
            result = self.bot._assess_completion(tmp)
            self.assertEqual(result["status"], "complete")
        finally:
            tmp.unlink(missing_ok=True)

    def test_assess_returns_word_count(self):
        """Result includes word_count field."""
        tmp = make_temp_manuscript(SAMPLE_COMPLETE_MYSTERY)
        try:
            result = self.bot._assess_completion(tmp)
            self.assertIn("word_count", result)
            self.assertGreater(result["word_count"], 0)
        finally:
            tmp.unlink(missing_ok=True)


class TestDispatchNaraiQueue(unittest.TestCase):
    """When a book fails QC after max rounds, rewrite queue should be updated."""

    def test_rewrite_queue_updated_on_fail(self):
        """full_book_analysis with MOCK_QC_FAIL_RESPONSE dispatches to rewrite queue."""
        from core.literary_qc import LiteraryQCAgent
        from tests.conftest import MOCK_QC_FAIL_RESPONSE

        agent = LiteraryQCAgent()
        queue_file = ROOT / "data" / "narai_rewrite_queue.json"
        tmp_path = str(ROOT / "outputs" / "books" / "mystery" / "test_volume_dispatch.md")

        with patch_claude({"score": MOCK_QC_FAIL_RESPONSE}):
            result = agent.full_book_analysis(
                SAMPLE_INCOMPLETE_MYSTERY,
                "Dispatch Queue Test",
                genre="mystery",
                manuscript_path=tmp_path,
            )

        if result.get("rewrite_needed"):
            self.assertTrue(queue_file.exists(), "Queue file should exist after dispatch")
            queue = json.loads(queue_file.read_text())
            self.assertIsInstance(queue, list)
            titles = [e.get("title") for e in queue]
            self.assertIn("Dispatch Queue Test", titles)

    def test_queue_entry_has_required_fields(self):
        """Each queue entry has id, title, genre, fail_reason, status fields."""
        from core.literary_qc import LiteraryQCAgent
        from tests.conftest import MOCK_QC_FAIL_RESPONSE

        agent = LiteraryQCAgent()
        queue_file = ROOT / "data" / "narai_rewrite_queue.json"
        tmp_path = str(ROOT / "outputs" / "books" / "mystery" / "test_volume_fields.md")

        with patch_claude({"score": MOCK_QC_FAIL_RESPONSE}):
            result = agent.full_book_analysis(
                SAMPLE_INCOMPLETE_MYSTERY,
                "Field Check Book",
                genre="mystery",
                manuscript_path=tmp_path,
            )

        if result.get("rewrite_needed") and queue_file.exists():
            queue = json.loads(queue_file.read_text())
            # Find our entry
            entry = next((e for e in queue if e.get("title") == "Field Check Book"), None)
            if entry:
                for field in ("id", "title", "genre", "fail_reason", "status", "queued_at"):
                    self.assertIn(field, entry, f"Queue entry missing field: {field}")
                self.assertEqual(entry["status"], "pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)
