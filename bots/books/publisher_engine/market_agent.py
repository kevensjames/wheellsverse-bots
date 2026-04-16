"""market_agent — generate titles, keywords, categories, Amazon KDP SEO optimization."""

PROMPT = """You are an Amazon KDP publishing expert and book marketing specialist.

Genre: {genre}
Current title: "{title}"

Story summary (first 2000 words):
{opening}

Your task: Optimize this book for maximum discoverability and sales on Amazon KDP.

Return JSON ONLY:
{{
  "titles": [
    "Title Option 1: Subtitle",
    "Title Option 2: Subtitle",
    "Title Option 3: Subtitle",
    "Title Option 4: Subtitle",
    "Title Option 5: Subtitle"
  ],
  "recommended_title": "Title Option 2: Subtitle",
  "subtitle": "The compelling subtitle (max 200 chars)",
  "series_name": "Series Name (if applicable)",
  "keywords": [
    "long-tail keyword 1 (max 50 chars)",
    "long-tail keyword 2",
    "long-tail keyword 3",
    "long-tail keyword 4",
    "long-tail keyword 5",
    "long-tail keyword 6",
    "long-tail keyword 7"
  ],
  "categories": [
    "Mystery, Thriller & Suspense > Mystery > Police Procedurals",
    "Mystery, Thriller & Suspense > Suspense > Psychological"
  ],
  "bisac_codes": ["FIC022060", "FIC030000"],
  "comparable_authors": ["Author 1", "Author 2"],
  "target_reader": "description of ideal reader",
  "pricing_recommendation": "$3.99",
  "seo_notes": "explanation of keyword strategy",
  "amazon_algorithm_tips": "specific tips for this book's launch"
}}

Keywords must be specific long-tail phrases readers actually search for on Amazon.
Titles must be catchy, genre-appropriate, and SEO-optimized."""


def run(manuscript: str, context: dict, bot) -> dict:
    """Generate market optimization: titles, keywords, categories."""
    genre = context.get("genre", "mystery")
    title = context.get("title", "untitled")

    # Use opening for context (most relevant for title/positioning)
    words = manuscript.split()
    opening = " ".join(words[:2000])

    prompt = (PROMPT.replace("{genre}", genre)
              .replace("{title}", title)
              .replace("{opening}", opening))

    try:
        result = bot.claude_json(prompt)
        result.setdefault("titles", [title])
        result.setdefault("keywords", [])
        result.setdefault("categories", [])
        # Enforce keyword limits (KDP max 7, each max 50 chars)
        result["keywords"] = [k[:50] for k in result["keywords"][:7]]
        result["categories"] = result["categories"][:2]
        return result
    except Exception as e:
        return {
            "titles": [title],
            "recommended_title": title,
            "subtitle": "",
            "series_name": "",
            "keywords": [f"{genre} fiction", "mystery thriller", "bestseller"],
            "categories": ["Mystery, Thriller & Suspense"],
            "comparable_authors": [],
            "target_reader": f"Fans of {genre} fiction",
            "pricing_recommendation": "$3.99",
            "seo_notes": f"Market analysis failed: {e}",
            "amazon_algorithm_tips": "",
            "error": str(e),
        }
