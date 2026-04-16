"""
tests/conftest.py
─────────────────────────────────────────────────────────────────────────────
Shared fixtures, sample texts, and Claude mock for the WheellsVerse test suite.
No real API calls — all Claude responses are stubbed.
"""
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ── Sample manuscripts ────────────────────────────────────────────────────────

CHAPTER_TEMPLATE = """## Chapter {n}: {title}

{body}

She sat back and surveyed the room. Everything was as it should be.
The case was finally over."""


def _make_chapter(n, title, body="Detective Sara Chen moved carefully through the darkened corridor. The clues were falling into place now, each revelation more startling than the last. She had followed the trail of stolen memories all the way to the Meridian Group's hidden laboratory. Mike Rodriguez stood at her shoulder, hand on his holster."):
    return CHAPTER_TEMPLATE.format(n=n, title=title, body=body)


SAMPLE_COMPLETE_MYSTERY = (
    "# The Memory Thief: Test Volume\n\n"
    "*By J.K. Blaze*\n\n"
    + "\n\n".join(_make_chapter(i, f"Chapter Title {i}") for i in range(1, 13))
    + "\n\n**THE END**\n\nAbout the Author\n\nJ.K. Blaze is a mystery fiction author."
)

SAMPLE_INCOMPLETE_MYSTERY = (
    "# Unfinished Case\n\n"
    "*By J.K. Blaze*\n\n"
    + "\n\n".join(_make_chapter(i, f"Chapter {i}") for i in range(1, 6))
    + "\n\n## Chapter 6: The Confrontation\n\nSara pushed open the door and saw Dr. James Cortex standing there, holding the memory device. She raised her gun and said, 'It's over, Cortex. Put down the"
)

SAMPLE_TOO_SHORT = "# Tiny Book\n\n*By J.K. Blaze*\n\nSara solved the case. The end.\n\n**THE END**"

SAMPLE_STUB_CHAPTERS = (
    "# Skeleton Book\n\n*By J.K. Blaze*\n\n"
    + "\n\n".join(
        f"## Chapter {i}: Title {i}\n\nSome words here." for i in range(1, 10)
    )
    + "\n\n**THE END**"
)

SAMPLE_VOL1_BIBLE = {
    "title": "The Memory Thief",
    "characters": [
        {"name": "Sara Chen", "role": "protagonist", "description": "Detective", "abilities": "analytical mind", "relationships": "partners with Rodriguez", "arc": "solves the case"},
        {"name": "Mike Rodriguez", "role": "supporting", "description": "Detective partner", "abilities": "loyal", "relationships": "partner to Sara", "arc": "supports Sara"},
        {"name": "Dr. James Cortex", "role": "antagonist", "description": "The Librarian", "abilities": "memory technology", "relationships": "leads Meridian Group", "arc": "defeated"},
    ],
    "plot_threads": [
        {"thread": "Who stole Elena Vasquez's memories", "introduced": "Chapter 1", "status": "resolved"},
        {"thread": "What is the Meridian Group", "introduced": "Chapter 3", "status": "unresolved"},
    ],
    "world_rules": ["Memory theft is possible via technology", "SFPD investigates unusual crimes"],
    "setting": "San Francisco",
    "tone": "dark mystery thriller",
    "cliffhanger": "But even as she said it,",
    "last_line": "But even as she said it,",
    "ending_status": "mid_sentence",
    "major_mysteries": ["The Meridian Group's true goal"],
    "resolved_mysteries": ["Who stole the memories"],
    "series_setup": "Sara is trapped as a cascade focal point",
    "word_count": 5545,
    "source_title": "The Memory Thief",
}


# ── Mock Claude ───────────────────────────────────────────────────────────────

MOCK_QC_PASS_RESPONSE = json.dumps({
    "score": 85,
    "issues": [],
    "verdict": "The manuscript meets quality standards.",
    "has_ending": True,
    "ending_type": "THE END marker present",
})

MOCK_QC_FAIL_RESPONSE = json.dumps({
    "score": 35,
    "issues": ["Story ends abruptly mid-sentence", "No resolution to main plot thread"],
    "verdict": "The manuscript ends mid-sentence and lacks a proper conclusion.",
    "has_ending": False,
})

MOCK_STORY_BIBLE_RESPONSE = json.dumps({
    "characters": [
        {"name": "Sara Chen", "role": "protagonist", "description": "Detective", "abilities": "sharp mind", "relationships": "partner with Rodriguez", "arc": "solves mystery"}
    ],
    "plot_threads": [{"thread": "Who stole memories", "introduced": "Ch 1", "status": "unresolved"}],
    "world_rules": ["Memory theft via tech"],
    "setting": "San Francisco",
    "tone": "dark mystery",
    "cliffhanger": "But even as she said it,",
    "last_line": "But even as she said it,",
    "ending_status": "mid_sentence",
    "major_mysteries": ["Meridian Group goal"],
    "resolved_mysteries": [],
    "series_setup": "Sara trapped",
})

MOCK_COMPARISON_RESPONSE = json.dumps({
    "protagonist_name_matches": True,
    "cliffhanger_resolved": True,
    "unauthorized_name_changes": [],
    "unauthorized_new_characters": [],
    "ability_changes": [],
    "world_rule_violations": [],
    "continuity_score": 88,
    "passed": True,
    "verdict": "PASS",
    "issues": [],
})

MOCK_COMPARISON_FAIL_RESPONSE = json.dumps({
    "protagonist_name_matches": False,
    "cliffhanger_resolved": False,
    "unauthorized_name_changes": ["Sara Chen → Elara Voss"],
    "unauthorized_new_characters": ["Lily (daughter)"],
    "ability_changes": [],
    "world_rule_violations": [],
    "continuity_score": 20,
    "passed": False,
    "verdict": "FAIL",
    "issues": ["Protagonist name changed from Sara Chen to Elara Voss"],
})

MOCK_AGENT_RESPONSES = {
    "story": json.dumps({"improved_manuscript": SAMPLE_COMPLETE_MYSTERY, "issues_fixed": ["pacing"], "structure_notes": "Good 3-act structure"}),
    "editing": json.dumps({"edited_manuscript": SAMPLE_COMPLETE_MYSTERY, "changes_made": 12, "readability_score": 82}),
    "style": json.dumps({"styled_manuscript": SAMPLE_COMPLETE_MYSTERY, "tone_notes": "Dark and atmospheric"}),
    "market": json.dumps({"titles": ["Title A", "Title B", "Title C", "Title D", "Title E"], "recommended_title": "Title A", "subtitle": "A Mystery", "keywords": ["mystery", "detective", "thriller", "crime", "fiction", "suspense", "noir"], "categories": ["Mystery", "Thriller"], "pricing_recommendation": "$3.99", "seo_notes": "Good SEO", "target_reader": "Mystery fans"}),
    "design": json.dumps({"cover_prompt": "Dark alley, detective, city lights", "color_palette": "dark blues", "spine_text": "Title A — J.K. Blaze", "layout_instructions": "Standard KDP format"}),
    "marketing": json.dumps({"description": "<p>A gripping mystery.</p>", "short_description": "A must-read thriller.", "tiktok_hooks": ["Hook 1", "Hook 2", "Hook 3"], "email_sequence": [], "sales_page": {"headline": "Title A", "subheadline": "", "bullet_points": [], "cta": "Buy Now", "faq": []}, "social_posts": {}}),
    "distribution": json.dumps({"kdp_metadata": {}, "gumroad_data": {}, "ready_to_publish": True, "validation_errors": []}),
}


@contextmanager
def patch_claude(response_map: dict = None):
    """
    Context manager that patches BaseBot.claude() and BaseBot.claude_json()
    to return fixture data instead of calling the Anthropic API.

    response_map: optional dict mapping prompt substrings to responses.
    If not provided, returns a generic passing QC response for all calls.
    """
    response_map = response_map or {}
    default_text = MOCK_QC_PASS_RESPONSE
    default_json = {"score": 85, "issues": [], "verdict": "Meets standards."}

    def _mock_claude(self, prompt, **kwargs):
        for key, val in response_map.items():
            if key.lower() in prompt.lower():
                return val
        return default_text

    def _mock_claude_json(self, prompt, **kwargs):
        for key, val in response_map.items():
            if key.lower() in prompt.lower():
                try:
                    return json.loads(val) if isinstance(val, str) else val
                except Exception:
                    return default_json
        try:
            return json.loads(default_text)
        except Exception:
            return default_json

    with patch("core.base_bot.BaseBot.claude", _mock_claude), \
         patch("core.base_bot.BaseBot.claude_json", _mock_claude_json):
        yield


def make_temp_manuscript(content: str) -> Path:
    """Write content to a temp .md file and return the path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)
