"""style_agent — enhance tone, improve dialogue rhythm, cinematic/emotional impact."""

GENRE_TONE = {
    "mystery": "cinematic, tense, atmospheric — Gillian Flynn meets Tana French",
    "thriller": "urgent, visceral, propulsive — James Patterson meets Dennis Lehane",
    "horror": "slow-burn dread, deeply unsettling — Stephen King meets Shirley Jackson",
    "romance": "emotionally charged, sensory-rich, yearning — Nicholas Sparks meets Sally Rooney",
    "sci_fi": "awe-inspiring, idea-driven, humanistic — Andy Weir meets Ursula K. Le Guin",
    "fantasy": "epic, mythic, world-building-rich — Brandon Sanderson meets N.K. Jemisin",
    "adventure": "kinetic, globe-trotting, fun — Indiana Jones meets Michael Crichton",
    "historical": "immersive period detail, epic scope — Hilary Mantel meets Ken Follett",
    "self_help": "empowering, practical, direct — Malcolm Gladwell meets Ryan Holiday",
    "true_crime": "journalistic, gripping, morally complex — Erik Larson meets Ann Rule",
    "childrens": "warm, wonder-filled, age-appropriate — Roald Dahl meets Lemony Snicket",
}

PROMPT = """You are a literary stylist specializing in {genre} fiction.

Target tone: {tone}

Manuscript title: "{title}"

Your task: Enhance the prose style without changing the story.

Focus on:
1. DIALOGUE — make it sharper, more natural, reveal character
2. SENSORY DETAIL — add specific sights, sounds, smells that ground scenes
3. EMOTIONAL RESONANCE — show don't tell; internalize emotions
4. RHYTHM — vary sentence length for tension (short=fast) and beauty (long=lyrical)
5. OPENING LINES — every chapter should open with a hook
6. VOICE — strengthen the narrative voice consistency

Do NOT change plot events, character names, or story outcomes.

Manuscript:
{manuscript}

Return JSON:
{{
  "styled_manuscript": "the full style-enhanced manuscript",
  "tone_notes": "description of style improvements made",
  "dialogue_improvements": ["specific dialogue changes"],
  "sensory_additions": "description of sensory details added",
  "emotional_beats_enhanced": ["moments improved for emotional impact"]
}}"""


def run(manuscript: str, context: dict, bot) -> dict:
    """Enhance tone and style."""
    genre = context.get("genre", "mystery")
    title = context.get("title", "untitled")
    tone = GENRE_TONE.get(genre, "engaging, well-paced, commercially publishable")

    words = manuscript.split()
    if len(words) > 15000:
        # Style the opening (most important) and ending — split at paragraph boundaries
        opening, middle, ending = _split_manuscript(manuscript, 7000, 5000)

        open_result = _style_section(opening, genre, title, tone, bot)
        end_result = _style_section(ending, genre, title, tone, bot)

        styled = (open_result.get("styled_manuscript", opening) +
                  "\n\n" + middle +
                  "\n\n" + end_result.get("styled_manuscript", ending))

        return {
            "styled_manuscript": styled,
            "tone_notes": f"Styled opening and ending. Tone: {tone}",
            "dialogue_improvements": (open_result.get("dialogue_improvements", []) +
                                      end_result.get("dialogue_improvements", [])),
            "sensory_additions": "Applied to opening and ending sections",
            "emotional_beats_enhanced": [],
        }

    prompt = (PROMPT.replace("{manuscript}", manuscript)
              .replace("{genre}", genre)
              .replace("{title}", title)
              .replace("{tone}", tone))
    try:
        result = bot.claude_json(prompt)
        if len(result.get("styled_manuscript", "").split()) < len(words) * 0.5:
            result["styled_manuscript"] = manuscript
        return result
    except Exception as e:
        return {
            "styled_manuscript": manuscript,
            "tone_notes": f"Style pass failed: {e}",
            "dialogue_improvements": [],
            "sensory_additions": "",
            "emotional_beats_enhanced": [],
            "error": str(e),
        }


def _split_manuscript(manuscript: str, opening_words: int, ending_words: int):
    """Split manuscript into opening/middle/ending at paragraph boundaries, preserving newlines."""
    paras = manuscript.split("\n\n")
    word_counts = [len(p.split()) for p in paras]

    cumulative = 0
    open_end = 0
    for i, wc in enumerate(word_counts):
        cumulative += wc
        if cumulative >= opening_words:
            open_end = i + 1
            break

    cumulative = 0
    end_start = len(paras)
    for i, wc in reversed(list(enumerate(word_counts))):
        cumulative += wc
        if cumulative >= ending_words:
            end_start = i
            break

    if end_start <= open_end:
        mid_point = (open_end + end_start) // 2
        open_end = mid_point
        end_start = mid_point

    opening = "\n\n".join(paras[:open_end])
    middle = "\n\n".join(paras[open_end:end_start])
    ending = "\n\n".join(paras[end_start:])
    return opening, middle, ending


def _style_section(section: str, genre: str, title: str, tone: str, bot) -> dict:
    prompt = (PROMPT.replace("{manuscript}", section)
              .replace("{genre}", genre)
              .replace("{title}", title)
              .replace("{tone}", tone))
    try:
        return bot.claude_json(prompt)
    except Exception as e:
        return {"styled_manuscript": section, "tone_notes": f"Failed: {e}",
                "dialogue_improvements": [], "sensory_additions": ""}
