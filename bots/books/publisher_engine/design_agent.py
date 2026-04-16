"""design_agent — book cover prompt, layout instructions, color palette, spine text."""

GENRE_COVER_STYLE = {
    "mystery": "Cinematic noir. Deep shadows, rain-soaked streets, lone figure, amber streetlight. Dark and tense.",
    "thriller": "High-contrast thriller aesthetic. Red and black. Urgency, danger, motion blur.",
    "horror": "Deeply unsettling. Victorian decay, blood moon, absolute silence. Desaturated with crimson.",
    "romance": "Soft golden hour. Two figures almost touching. Rose gold and champagne palette.",
    "sci_fi": "Vast cosmic scale. Neon blues and electric cyan against deep black space. Awe-inspiring.",
    "fantasy": "Epic fantasy. Dragons, glowing magic, ancient towers, twilight sky. Deep purples and gold.",
    "adventure": "Golden-hour jungle canyon. Lost temples, dramatic landscape. Greens and warm sunset gold.",
    "historical": "Baroque oil painting style. Candlelit palace or battlefield. Deep reds, gold, ivory.",
    "self_help": "Bold minimalist. Single powerful symbol. Vibrant gradient. Inspirational.",
    "true_crime": "Documentary aesthetic. Crime scene, newspaper, dark red. Stark urgency.",
    "childrens": "Magical watercolor. Bright colors, adorable characters, wonder and adventure.",
}

PROMPT = """You are a professional book cover designer and formatter.

Genre: {genre}
Title: "{title}"
Cover style guide: {style}

Story synopsis:
{synopsis}

Return JSON ONLY:
{{
  "cover_prompt": "Ultra-detailed DALL-E 3 prompt for the cover illustration. Must be commercially publishable. NO text in the image. Describe lighting, mood, composition, color palette, art style in detail.",
  "cover_concept": "Brief description of the visual concept",
  "color_palette": {{
    "primary": "#hex",
    "secondary": "#hex",
    "accent": "#hex",
    "background": "#hex",
    "mood": "description"
  }},
  "typography": {{
    "title_font": "font recommendation for title",
    "author_font": "font recommendation for author name",
    "title_treatment": "how to style the title text on the cover"
  }},
  "spine_text": "Title | Author Name",
  "back_cover_blurb": "200-word back cover blurb that sells the book",
  "layout_instructions": {{
    "kdp_specs": "2560 x 1600px full bleed, 300dpi, RGB, JPEG",
    "cover_area": "front cover: right half",
    "title_placement": "upper third, centered",
    "author_placement": "bottom, centered",
    "series_badge": "top left corner if series"
  }},
  "epub_formatting": {{
    "chapter_style": "CSS for chapter headings",
    "body_font": "serif recommendation",
    "line_height": "1.6",
    "margins": "standard KDP margins"
  }}
}}"""


def run(manuscript: str, context: dict, bot) -> dict:
    """Generate cover design brief and layout instructions."""
    genre = context.get("genre", "mystery")
    title = context.get("title", "untitled")
    style = GENRE_COVER_STYLE.get(genre, "Professional book cover, high quality, commercially publishable.")

    words = manuscript.split()
    synopsis = " ".join(words[:500])  # First 500 words for cover context

    prompt = (PROMPT.replace("{genre}", genre)
              .replace("{title}", title)
              .replace("{style}", style)
              .replace("{synopsis}", synopsis))

    try:
        result = bot.claude_json(prompt)
        result.setdefault("cover_prompt", f"Professional {genre} book cover for '{title}'. {style} No text.")
        return result
    except Exception as e:
        return {
            "cover_prompt": (
                f"Professional Amazon Kindle book cover for '{title}'. Genre: {genre}. "
                f"{style} Ultra high quality, commercially publishable. "
                "Absolutely NO text in the image."
            ),
            "cover_concept": f"{genre.title()} cover",
            "color_palette": {"primary": "#1a1a2e", "secondary": "#e94560",
                              "accent": "#f5a623", "background": "#0f3460", "mood": "dark"},
            "typography": {"title_font": "Playfair Display Bold",
                           "author_font": "Garamond", "title_treatment": "Large centered"},
            "spine_text": f"{title} | J.K. Blaze",
            "back_cover_blurb": "",
            "layout_instructions": {"kdp_specs": "2560x1600px, 300dpi, RGB, JPEG"},
            "epub_formatting": {"body_font": "Georgia", "line_height": "1.6"},
            "error": str(e),
        }
