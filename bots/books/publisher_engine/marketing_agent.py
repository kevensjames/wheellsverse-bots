"""marketing_agent — product description, TikTok hooks, email sequence, sales page."""

PROMPT = """You are a bestselling book marketer specializing in digital sales.

Genre: {genre}
Title: "{title}"
Target readers: {target_reader}
Price: {price}

Story synopsis (first 1000 words):
{synopsis}

Create complete marketing content. Return JSON ONLY:
{{
  "description": "<h2>HTML-formatted KDP product description (max 4000 chars)</h2><p>Hook paragraph...</p><p>Story beats...</p><p>Perfect for fans of...</p><p><strong>Scroll up and grab your copy today.</strong></p>",
  "short_description": "One-sentence hook for social media (max 150 chars)",
  "tiktok_hooks": [
    "Hook 1: POV story opener (under 150 chars)",
    "Hook 2: Controversial/surprising statement",
    "Hook 3: 'The book that made me...' style"
  ],
  "email_sequence": [
    {{
      "day": 0,
      "subject": "Subject line for launch day email",
      "preview": "Preview text (max 90 chars)",
      "body": "Full email body (200-300 words)"
    }},
    {{
      "day": 1,
      "subject": "Day 2 follow-up subject",
      "preview": "Preview text",
      "body": "Follow-up email body"
    }},
    {{
      "day": 3,
      "subject": "Social proof email subject",
      "preview": "Preview text",
      "body": "Reader reactions / testimonials email"
    }},
    {{
      "day": 7,
      "subject": "Last chance / urgency email",
      "preview": "Preview text",
      "body": "Urgency email body"
    }},
    {{
      "day": 14,
      "subject": "Series announcement / next book",
      "preview": "Preview text",
      "body": "Tease of next book"
    }}
  ],
  "sales_page": {{
    "headline": "Main sales page headline",
    "subheadline": "Supporting subheadline",
    "bullet_points": ["Benefit 1", "Benefit 2", "Benefit 3", "Benefit 4", "Benefit 5"],
    "cta": "Call to action text",
    "faq": [
      {{"q": "Who is this book for?", "a": "answer"}},
      {{"q": "Is this a series?", "a": "answer"}}
    ]
  }},
  "social_posts": {{
    "facebook": "Facebook post (200 words, 3-5 hashtags)",
    "instagram": "Instagram caption (100 words + 20 hashtags)",
    "twitter": "Tweet thread (3 tweets)"
  }}
}}

The description must use HTML tags as KDP accepts HTML in descriptions."""


def run(manuscript: str, context: dict, bot) -> dict:
    """Generate full marketing content package."""
    genre = context.get("genre", "mystery")
    title = context.get("title", "untitled")
    price = context.get("pricing_recommendation",
              context.get("market_agent", {}).get("pricing_recommendation", "$3.99"))
    target = context.get("market_agent", {}).get("target_reader", f"fans of {genre} fiction")

    words = manuscript.split()
    synopsis = " ".join(words[:1000])

    prompt = (PROMPT.replace("{genre}", genre)
              .replace("{title}", title)
              .replace("{target_reader}", target)
              .replace("{price}", str(price))
              .replace("{synopsis}", synopsis))

    try:
        result = bot.claude_json(prompt)
        result.setdefault("description", f"<p>A compelling {genre} novel: {title}</p>")
        result.setdefault("tiktok_hooks", [])
        result.setdefault("email_sequence", [])
        return result
    except Exception as e:
        return {
            "description": f"<p>A gripping {genre} novel. {title} by J.K. Blaze.</p>",
            "short_description": f"A must-read {genre} thriller.",
            "tiktok_hooks": [f"This {genre} book will keep you up all night..."],
            "email_sequence": [],
            "sales_page": {"headline": title, "subheadline": "", "bullet_points": [],
                           "cta": "Buy Now", "faq": []},
            "social_posts": {},
            "error": str(e),
        }
