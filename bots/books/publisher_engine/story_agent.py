"""story_agent — improve plot structure, fix pacing, detect inconsistencies."""

PROMPT = """You are a senior developmental editor specializing in {genre} fiction.

Manuscript title: "{title}"

Your task: Improve the plot structure, fix pacing issues, and detect/correct inconsistencies.

Focus on:
1. THREE-ACT STRUCTURE — ensure clear setup, confrontation, resolution
2. PACING — cut dead scenes, add tension to slow spots, smooth rushed passages
3. CHAPTER HOOKS — every chapter should end pulling the reader forward
4. INCONSISTENCIES — flag and fix plot holes, contradictions, logic errors
5. OPENING — first paragraph must hook the reader immediately
6. CLIMAX — must be earned, not rushed

IMPORTANT: Keep all character names, abilities, and world rules exactly as written.
Do not change the story — improve how it's told.

Manuscript:
{manuscript}

Return a JSON object:
{{
  "improved_manuscript": "the full improved manuscript text",
  "issues_fixed": ["list of specific issues you found and fixed"],
  "structure_notes": "brief analysis of the three-act structure",
  "pacing_changes": "description of pacing improvements made",
  "word_count_delta": 0
}}"""


def run(manuscript: str, context: dict, bot) -> dict:
    """Improve plot structure and pacing."""
    genre = context.get("genre", "mystery")
    title = context.get("title", "untitled")

    # For very long manuscripts, process in chunks (split at paragraph boundaries)
    words = manuscript.split()
    if len(words) > 20000:
        # Focus on structure analysis — sample opening + ending paragraphs, preserve newlines
        paras = manuscript.split("\n\n")
        # Approx first 8000 words: walk paragraphs
        opening_paras, cumwc = [], 0
        for p in paras:
            opening_paras.append(p)
            cumwc += len(p.split())
            if cumwc >= 8000:
                break
        ending_paras, cumwc = [], 0
        for p in reversed(paras):
            ending_paras.insert(0, p)
            cumwc += len(p.split())
            if cumwc >= 4000:
                break
        sample = "\n\n".join(opening_paras) + "\n\n[...]\n\n" + "\n\n".join(ending_paras)
        analysis_prompt = PROMPT.replace("{manuscript}", sample)
    else:
        analysis_prompt = PROMPT.replace("{manuscript}", manuscript)

    analysis_prompt = analysis_prompt.replace("{genre}", genre).replace("{title}", title)

    try:
        result = bot.claude_json(analysis_prompt)
        # If improved_manuscript is empty or very short, keep original
        improved = result.get("improved_manuscript", "")
        if len(improved.split()) < len(words) * 0.5:
            result["improved_manuscript"] = manuscript
            result.setdefault("issues_fixed", [])
            result["note"] = "Manuscript too long for full rewrite — analysis only"
        return result
    except Exception as e:
        return {
            "improved_manuscript": manuscript,
            "issues_fixed": [],
            "structure_notes": f"Analysis failed: {e}",
            "pacing_changes": "",
            "word_count_delta": 0,
            "error": str(e),
        }
