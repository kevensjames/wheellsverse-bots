"""tests/test_publisher_pipeline.py — Publisher Engine pipeline unit tests."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.conftest import SAMPLE_COMPLETE_MYSTERY, patch_claude  # noqa: E402


AGENT_MODULES = [
    "story_agent", "editing_agent", "style_agent",
    "market_agent", "design_agent", "marketing_agent", "distribution_agent",
]


class TestPublisherEngineImports(unittest.TestCase):
    def test_pipeline_import(self):
        from bots.books.publisher_engine.pipeline import PublisherEnginePipeline
        self.assertTrue(callable(PublisherEnginePipeline))

    def test_all_agent_imports(self):
        for name in AGENT_MODULES:
            with self.subTest(agent=name):
                mod = __import__(f"bots.books.publisher_engine.{name}",
                                 fromlist=[name])
                self.assertTrue(hasattr(mod, "run"), f"{name} missing run()")

    def test_init_import(self):
        import bots.books.publisher_engine
        self.assertIsNotNone(bots.books.publisher_engine)


class TestIndividualAgents(unittest.TestCase):
    """Each agent's run() should return a dict with required keys."""

    def _make_bot(self):
        from core.base_bot import BaseBot
        bot = MagicMock(spec=BaseBot)
        bot.logger = MagicMock()
        bot.claude = MagicMock(return_value=SAMPLE_COMPLETE_MYSTERY)
        bot.claude_json = MagicMock(return_value={"improved_manuscript": SAMPLE_COMPLETE_MYSTERY, "issues_fixed": [], "structure_notes": "ok", "edited_manuscript": SAMPLE_COMPLETE_MYSTERY, "changes_made": 5, "readability_score": 80, "styled_manuscript": SAMPLE_COMPLETE_MYSTERY, "tone_notes": "dark", "titles": ["T1", "T2", "T3", "T4", "T5"], "recommended_title": "T1", "subtitle": "Sub", "keywords": ["k1", "k2", "k3", "k4", "k5", "k6", "k7"], "categories": ["Mystery", "Thriller"], "pricing_recommendation": "$3.99", "seo_notes": "ok", "target_reader": "fans", "cover_prompt": "dark city", "color_palette": "blues", "spine_text": "T1", "layout_instructions": "standard", "description": "<p>Good book.</p>", "short_description": "A thriller.", "tiktok_hooks": ["h1", "h2", "h3"], "email_sequence": [], "sales_page": {"headline": "T1", "subheadline": "", "bullet_points": [], "cta": "Buy", "faq": []}, "social_posts": {}})
        return bot

    def test_story_agent_keys(self):
        from bots.books.publisher_engine import story_agent
        bot = self._make_bot()
        ctx = {"genre": "mystery", "title": "Test", "author": "J.K. Blaze", "ts": "20260411"}
        result = story_agent.run(SAMPLE_COMPLETE_MYSTERY, ctx, bot)
        self.assertIsInstance(result, dict)

    def test_editing_agent_keys(self):
        from bots.books.publisher_engine import editing_agent
        bot = self._make_bot()
        ctx = {"genre": "mystery", "title": "Test", "author": "J.K. Blaze", "ts": "20260411"}
        result = editing_agent.run(SAMPLE_COMPLETE_MYSTERY, ctx, bot)
        self.assertIsInstance(result, dict)

    def test_market_agent_keys(self):
        from bots.books.publisher_engine import market_agent
        bot = self._make_bot()
        ctx = {"genre": "mystery", "title": "Test", "author": "J.K. Blaze", "ts": "20260411"}
        result = market_agent.run(SAMPLE_COMPLETE_MYSTERY, ctx, bot)
        self.assertIsInstance(result, dict)
        self.assertIn("titles", result)
        self.assertIn("keywords", result)

    def test_design_agent_keys(self):
        from bots.books.publisher_engine import design_agent
        bot = self._make_bot()
        ctx = {"genre": "mystery", "title": "Test", "author": "J.K. Blaze", "ts": "20260411"}
        result = design_agent.run(SAMPLE_COMPLETE_MYSTERY, ctx, bot)
        self.assertIsInstance(result, dict)
        self.assertIn("cover_prompt", result)

    def test_marketing_agent_keys(self):
        from bots.books.publisher_engine import marketing_agent
        bot = self._make_bot()
        ctx = {"genre": "mystery", "title": "Test", "author": "J.K. Blaze", "ts": "20260411",
               "market_agent": {"target_reader": "fans", "pricing_recommendation": "$3.99"}}
        result = marketing_agent.run(SAMPLE_COMPLETE_MYSTERY, ctx, bot)
        self.assertIsInstance(result, dict)
        self.assertIn("description", result)


class TestPipelineOrchestration(unittest.TestCase):
    def setUp(self):
        from bots.books.publisher_engine.pipeline import PublisherEnginePipeline
        self.pipeline = PublisherEnginePipeline()

    def test_skip_agents(self):
        """skip_agents param prevents those agents from running."""
        skip = ["story_agent", "editing_agent", "style_agent",
                "market_agent", "design_agent", "marketing_agent", "distribution_agent"]
        with patch_claude():
            result = self.pipeline.process(
                manuscript=SAMPLE_COMPLETE_MYSTERY,
                title="Skip Test",
                genre="mystery",
                skip_agents=skip,
                skip_word_check=True,
            )
        # All agents skipped — result should still be a dict
        self.assertIsInstance(result, dict)
        for name in skip:
            self.assertTrue(result.get("agents", {}).get(name, {}).get("skipped"), f"{name} should be skipped")

    def test_status_file_written(self):
        """After process(), status file should exist."""
        skip_all = ["story_agent", "editing_agent", "style_agent",
                    "market_agent", "design_agent", "marketing_agent", "distribution_agent"]
        with patch_claude():
            self.pipeline.process(
                manuscript=SAMPLE_COMPLETE_MYSTERY,
                title="Status Test",
                genre="mystery",
                skip_agents=skip_all,
                skip_word_check=True,
            )
        status_file = ROOT / "data" / "publisher_engine_status.json"
        self.assertTrue(status_file.exists())

    def test_result_keys(self):
        skip_all = ["story_agent", "editing_agent", "style_agent",
                    "market_agent", "design_agent", "marketing_agent", "distribution_agent"]
        with patch_claude():
            result = self.pipeline.process(
                manuscript=SAMPLE_COMPLETE_MYSTERY,
                title="Keys Test",
                genre="mystery",
                skip_agents=skip_all,
                skip_word_check=True,
            )
        for key in ("title", "genre", "original_words", "final_words", "agents", "ts"):
            self.assertIn(key, result, f"Missing key: {key}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
