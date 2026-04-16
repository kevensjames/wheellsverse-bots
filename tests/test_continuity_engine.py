"""tests/test_continuity_engine.py — ContinuityEngine unit tests."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.conftest import (  # noqa: E402
    SAMPLE_COMPLETE_MYSTERY, SAMPLE_VOL1_BIBLE,
    MOCK_STORY_BIBLE_RESPONSE, MOCK_COMPARISON_RESPONSE, MOCK_COMPARISON_FAIL_RESPONSE,
    patch_claude, make_temp_manuscript,
)


class TestContinuityEngineImport(unittest.TestCase):
    def test_import(self):
        from core.continuity_engine import ContinuityEngine
        self.assertTrue(callable(ContinuityEngine))

    def test_instantiate(self):
        from core.continuity_engine import ContinuityEngine
        engine = ContinuityEngine()
        self.assertIsNotNone(engine)


class TestExtractStoryBible(unittest.TestCase):
    def setUp(self):
        from core.continuity_engine import ContinuityEngine
        self.engine = ContinuityEngine()

    def test_returns_dict(self):
        with patch_claude({"character": MOCK_STORY_BIBLE_RESPONSE}):
            result = self.engine.extract_story_bible(SAMPLE_COMPLETE_MYSTERY, "Test Book")
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        with patch_claude({"character": MOCK_STORY_BIBLE_RESPONSE}):
            result = self.engine.extract_story_bible(SAMPLE_COMPLETE_MYSTERY, "Test Book")
        for key in ("characters", "plot_threads", "world_rules", "cliffhanger",
                    "setting", "tone", "ending_status"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_title_stored(self):
        with patch_claude({"character": MOCK_STORY_BIBLE_RESPONSE}):
            result = self.engine.extract_story_bible(SAMPLE_COMPLETE_MYSTERY, "My Mystery")
        self.assertEqual(result.get("title") or result.get("source_title"), "My Mystery")

    def test_caching(self):
        """Second call with same title uses cache — no additional Claude call."""
        call_count = [0]

        def counting_claude(prompt, **kwargs):
            call_count[0] += 1
            return json.loads(MOCK_STORY_BIBLE_RESPONSE)

        import unittest.mock as mock
        with mock.patch.object(self.engine, "claude_json", counting_claude):
            self.engine.extract_story_bible(SAMPLE_COMPLETE_MYSTERY, "Cached Book")
            first_count = call_count[0]
            self.engine.extract_story_bible(SAMPLE_COMPLETE_MYSTERY, "Cached Book")
            # Second call should not add more Claude calls (cache hit)
            self.assertEqual(call_count[0], first_count)

    def test_extract_from_file(self):
        tmp = make_temp_manuscript(SAMPLE_COMPLETE_MYSTERY)
        try:
            with patch_claude({"character": MOCK_STORY_BIBLE_RESPONSE}):
                result = self.engine.extract_from_file(str(tmp))
            self.assertIsInstance(result, dict)
        finally:
            tmp.unlink(missing_ok=True)


class TestCompareVolumes(unittest.TestCase):
    def setUp(self):
        from core.continuity_engine import ContinuityEngine
        self.engine = ContinuityEngine()

    def test_compare_pass_returns_dict(self):
        vol2 = SAMPLE_COMPLETE_MYSTERY
        with patch_claude({"protagonist": MOCK_COMPARISON_RESPONSE}):
            result = self.engine.compare_volumes(SAMPLE_VOL1_BIBLE, vol2)
        self.assertIsInstance(result, dict)

    def test_compare_pass_score(self):
        """Matching protagonist → high continuity score."""
        vol2 = SAMPLE_COMPLETE_MYSTERY  # contains "Sara Chen"
        with patch_claude({"protagonist": MOCK_COMPARISON_RESPONSE}):
            result = self.engine.compare_volumes(SAMPLE_VOL1_BIBLE, vol2)
        self.assertGreaterEqual(result.get("continuity_score", 0), 70)
        self.assertTrue(result.get("passed"))

    def test_compare_fail_wrong_protagonist(self):
        """Wrong protagonist → low score, failed."""
        vol2_wrong = SAMPLE_COMPLETE_MYSTERY.replace("Sara Chen", "Elara Voss")
        with patch_claude({"protagonist": MOCK_COMPARISON_FAIL_RESPONSE}):
            result = self.engine.compare_volumes(SAMPLE_VOL1_BIBLE, vol2_wrong)
        self.assertFalse(result.get("passed", True))
        self.assertLess(result.get("continuity_score", 100), 70)

    def test_generate_report(self):
        with patch_claude({"protagonist": MOCK_COMPARISON_RESPONSE}):
            comparison = self.engine.compare_volumes(SAMPLE_VOL1_BIBLE, SAMPLE_COMPLETE_MYSTERY)
        report = self.engine.generate_continuity_report(comparison)
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
