"""distribution_agent — KDP-ready package, Gumroad data, cover generation, HTML export."""
import re
from pathlib import Path
from datetime import datetime


def run(manuscript: str, context: dict, bot) -> dict:
    """Build KDP-ready package and distribution metadata."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

    genre = context.get("genre", "mystery")
    title = context.get("title", "untitled")
    author = context.get("author", "J.K. Blaze")
    ts = context.get("ts", datetime.now().strftime("%Y%m%d_%H%M%S"))
    safe_title = re.sub(r"[^\w]+", "_", title.lower())[:40]

    # Pull from upstream agents
    market = context.get("market_agent", {})
    marketing = context.get("marketing_agent", {})
    design = context.get("design_agent", {})

    keywords = market.get("keywords", [f"{genre} fiction"])[:7]
    description = marketing.get("description", f"<p>A compelling {genre} novel.</p>")
    categories = market.get("categories", ["Mystery, Thriller & Suspense"])[:2]
    price_str = market.get("pricing_recommendation", "$3.99")
    cover_prompt = design.get("cover_prompt", "")

    try:
        price = float(price_str.replace("$", ""))
    except Exception:
        price = 3.99

    # ── KDP Metadata ─────────────────────────────────────────────────────────
    kdp_metadata = {
        "title": title,
        "subtitle": market.get("subtitle", ""),
        "series": market.get("series_name", ""),
        "author": author,
        "description_html": description,
        "keywords": keywords,
        "categories": categories,
        "price": price,
        "language": "en",
        "genre": genre,
    }

    # ── Validate with KDPValidator ────────────────────────────────────────────
    validation_errors = []
    try:
        from core.kdp_validator import KDPValidator
        validator = KDPValidator()
        result_v = validator.validate(
            genre=genre,
            title=title,
            author=author,
            description=re.sub(r"<[^>]+>", "", description),  # strip HTML for validation
            keywords=keywords,
            price=price,
        )
        if not result_v.is_valid:
            validation_errors = result_v.errors
    except Exception as e:
        validation_errors = [f"Validator error: {e}"]

    # ── Generate Cover (DALL-E 3) ─────────────────────────────────────────────
    cover_path = None
    try:
        from core.kdp_uploader import generate_cover
        cover_path = str(generate_cover(title, genre, dall_e_prompt=cover_prompt or None))
        bot.logger.info("Cover generated: %s", cover_path)
    except Exception as e:
        bot.logger.warning("Cover generation failed: %s", e)

    # ── Package HTML ──────────────────────────────────────────────────────────
    html_path = _package_html(manuscript, title, author, cover_path, description, ts, safe_title)

    # ── Write KDP Package metadata file ──────────────────────────────────────
    out_dir = Path(__file__).resolve().parents[3] / "outputs" / "books" / "published"
    out_dir.mkdir(parents=True, exist_ok=True)
    pkg_path = out_dir / f"{genre}_{safe_title}_{ts}_kdp_package.md"
    pkg_path.write_text(_build_kdp_package_md(kdp_metadata), encoding="utf-8")

    # ── Gumroad metadata ──────────────────────────────────────────────────────
    short_desc = marketing.get("short_description", f"A gripping {genre} novel.")
    gumroad_data = {
        "name": title,
        "price_cents": int(price * 100),
        "description": short_desc,
        "tags": keywords[:10],
        "file_type": "pdf",
        "custom_permalink": safe_title.replace("_", "-"),
    }

    ready = len(validation_errors) == 0 and html_path is not None

    return {
        "kdp_metadata": kdp_metadata,
        "gumroad_data": gumroad_data,
        "html_path": str(html_path) if html_path else None,
        "cover_path": cover_path,
        "kdp_package_path": str(pkg_path),
        "validation_errors": validation_errors,
        "ready_to_publish": ready,
        "price": price,
    }


def _package_html(manuscript: str, title: str, author: str,
                   cover_path, description: str, ts: str, safe_title: str) -> Path | None:
    """Convert manuscript markdown to KDP-ready HTML."""
    import re as _re
    import base64
    from pathlib import Path as _Path

    out_dir = _Path(__file__).resolve().parents[3] / "outputs" / "books" / "packaged"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{safe_title}_{ts}.html"

    lines = manuscript.split("\n")
    body = []
    for line in lines:
        if line.startswith("# "):
            body.append(f'<h1 class="title">{line[2:]}</h1>')
        elif line.startswith("## "):
            body.append(f'<h2 class="chapter">{line[3:]}</h2>')
        elif line.startswith("### "):
            body.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith("**") and line.endswith("**"):
            body.append(f'<p class="center"><strong>{line[2:-2]}</strong></p>')
        elif line.startswith("*") and line.endswith("*") and not line.startswith("**"):
            body.append(f'<p class="center"><em>{line[1:-1]}</em></p>')
        elif line.strip() == "---":
            body.append("<hr>")
        elif line.strip() == "":
            body.append("<p>&nbsp;</p>")
        else:
            line = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            line = _re.sub(r"\*(.+?)\*", r"<em>\1</em>", line)
            body.append(f"<p>{line}</p>")

    cover_html = ""
    if cover_path and _Path(str(cover_path)).exists():
        try:
            with open(cover_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = _Path(str(cover_path)).suffix.lstrip(".").lower() or "jpeg"
            cover_html = (
                f'<div class="cover-page">'
                f'<img src="data:image/{ext};base64,{b64}" alt="Cover — {title}">'
                f"</div>"
            )
        except Exception:
            pass

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body{{font-family:Georgia,'Times New Roman',serif;max-width:700px;margin:0 auto;
       padding:40px 30px;line-height:1.9;color:#1a1a1a;font-size:16px}}
  h1.title{{text-align:center;font-size:2.2em;margin:60px 0 10px;color:#111}}
  h2.chapter{{font-size:1.4em;margin:60px 0 20px;border-bottom:2px solid #222;
              padding-bottom:8px;color:#111;page-break-before:always}}
  h3{{font-size:1.1em;color:#444;margin:30px 0 10px}}
  p{{margin:0 0 1.1em;text-indent:1.5em}}
  p.center{{text-align:center;text-indent:0;font-style:italic;color:#444}}
  hr{{border:none;border-top:1px solid #bbb;margin:50px auto;width:35%}}
  .cover-page{{text-align:center;page-break-after:always;margin-bottom:60px}}
  .cover-page img{{max-width:100%;max-height:90vh;box-shadow:0 8px 32px rgba(0,0,0,.35)}}
  @media print{{body{{font-size:12pt;max-width:none;padding:0}}
                h2.chapter{{page-break-before:always}}}}
</style>
</head>
<body>
{cover_html}
{'\n'.join(body)}
</body>
</html>"""

    html_path.write_text(html, encoding="utf-8")
    return html_path


def _build_kdp_package_md(meta: dict) -> str:
    keywords_block = "\n".join(f"{i + 1}. {k}" for i, k in enumerate(meta.get("keywords", [])))
    return f"""# KDP Package — {meta['title']}

**BOOK TITLE:** {meta['title']}
**Subtitle:** {meta.get('subtitle', '')}
**Series:** {meta.get('series', '')}
**Author:** {meta.get('author', 'J.K. Blaze')}
**Genre:** {meta.get('genre', '').replace('_', ' ').title()}
**Price:** ${meta.get('price', 3.99):.2f}
**Language:** {meta.get('language', 'en')}

## Description

{meta.get('description_html', '')}

## KEYWORDS
{keywords_block}

## Categories
{chr(10).join(meta.get('categories', []))}
"""
