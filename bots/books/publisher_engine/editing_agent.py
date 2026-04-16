"""editing_agent — fix grammar, clarity, readability while preserving voice."""

PROMPT = """You are a professional copy editor for {genre} fiction.

Manuscript title: "{title}"

Your task: Fix grammar, punctuation, clarity, and readability.

Rules:
- PRESERVE the author's voice and style
- PRESERVE all character names, plot events, and story details
- Fix: grammar errors, run-on sentences, unclear pronoun references, awkward phrasing
- Fix: inconsistent tense, redundant words, passive voice overuse
- Do NOT rewrite scenes — only polish the language

Manuscript:
{manuscript}

Return JSON:
{{
  "edited_manuscript": "the full edited manuscript",
  "changes_made": 42,
  "readability_score": 75,
  "major_grammar_fixes": ["list of significant fixes"],
  "style_notes": "brief notes on editing approach"
}}
readability_score is 0-100 (higher = more accessible)."""


def run(manuscript: str, context: dict, bot) -> dict:
    """Fix grammar and readability."""
    genre = context.get("genre", "mystery")
    title = context.get("title", "untitled")

    # For long manuscripts, edit in sections (split by paragraphs to preserve newlines)
    words = manuscript.split()
    if len(words) > 15000:
        opening_section, middle_section, ending_section = _split_manuscript(manuscript, 6000, 4000)

        opening_result = _edit_section(opening_section, genre, title, bot, "opening")
        ending_result = _edit_section(ending_section, genre, title, bot, "ending")

        edited = (opening_result.get("edited_manuscript", opening_section) +
                  "\n\n" + middle_section +
                  "\n\n" + ending_result.get("edited_manuscript", ending_section))

        return {
            "edited_manuscript": edited,
            "changes_made": (opening_result.get("changes_made", 0) +
                             ending_result.get("changes_made", 0)),
            "readability_score": max(
                opening_result.get("readability_score", 70),
                ending_result.get("readability_score", 70),
            ),
            "major_grammar_fixes": (opening_result.get("major_grammar_fixes", []) +
                                    ending_result.get("major_grammar_fixes", [])),
            "style_notes": "Long manuscript — edited opening and ending sections",
        }

    prompt = PROMPT.replace("{manuscript}", manuscript).replace("{genre}", genre).replace("{title}", title)
    try:
        result = bot.claude_json(prompt)
        if len(result.get("edited_manuscript", "").split()) < len(words) * 0.5:
            result["edited_manuscript"] = manuscript
        return result
    except Exception as e:
        return {
            "edited_manuscript": manuscript,
            "changes_made": 0,
            "readability_score": 60,
            "major_grammar_fixes": [],
            "style_notes": f"Editing failed: {e}",
            "error": str(e),
        }


def _split_manuscript(manuscript: str, opening_words: int, ending_words: int):
    """Split manuscript into opening/middle/ending at paragraph boundaries, preserving newlines."""
    paras = manuscript.split("\n\n")
    word_counts = [len(p.split()) for p in paras]

    # Find paragraph index where opening ends (~opening_words words in)
    cumulative = 0
    open_end = 0
    for i, wc in enumerate(word_counts):
        cumulative += wc
        if cumulative >= opening_words:
            open_end = i + 1
            break

    # Find paragraph index where ending starts (~ending_words words from end)
    cumulative = 0
    end_start = len(paras)
    for i, wc in reversed(list(enumerate(word_counts))):
        cumulative += wc
        if cumulative >= ending_words:
            end_start = i
            break

    # Ensure non-overlapping
    if end_start <= open_end:
        mid_point = (open_end + end_start) // 2
        open_end = mid_point
        end_start = mid_point

    opening = "\n\n".join(paras[:open_end])
    middle = "\n\n".join(paras[open_end:end_start])
    ending = "\n\n".join(paras[end_start:])
    return opening, middle, ending


def _edit_section(section: str, genre: str, title: str, bot, label: str) -> dict:
    prompt = PROMPT.replace("{manuscript}", section).replace("{genre}", genre).replace("{title}", f"{title} ({label})")
    try:
        return bot.claude_json(prompt)
    except Exception as e:
        return {"edited_manuscript": section, "changes_made": 0,
                "readability_score": 60, "major_grammar_fixes": [], "error": str(e)}
