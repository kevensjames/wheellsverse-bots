#!/usr/bin/env python3
"""
scripts/generate_blog_index.py
─────────────────────────────────────────────────────────────────────────────
Scans frontend/blog/*.html and auto-generates:
  • frontend/blog/index.html  — beautiful card-grid listing of all posts
  • frontend/sitemap.xml      — XML sitemap for Google indexing

Run after every publish:
  python scripts/generate_blog_index.py
"""

import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
BLOG_DIR = ROOT / "frontend" / "blog"
SITE_URL = "https://wheellsverse-bots.pages.dev"

CATEGORY_MAP = {
    "crypto": ("Crypto", "#00d4ff", "₿"),
    "bitcoin": ("Crypto", "#00d4ff", "₿"),
    "coinbase": ("Crypto", "#00d4ff", "₿"),
    "binance": ("Crypto", "#00d4ff", "₿"),
    "ethereum": ("Crypto", "#00d4ff", "₿"),
    "stock": ("Stocks", "#00ff88", "📈"),
    "robinhood": ("Stocks", "#00ff88", "📈"),
    "invest": ("Stocks", "#00ff88", "📈"),
    "dividend": ("Stocks", "#00ff88", "📈"),
    "passive": ("Passive Income", "#ffd700", "💰"),
    "income": ("Passive Income", "#ffd700", "💰"),
    "ai-tool": ("AI Tools", "#a78bfa", "🤖"),
    "ai_tool": ("AI Tools", "#a78bfa", "🤖"),
    "chatgpt": ("AI Tools", "#a78bfa", "🤖"),
    "automat": ("AI Tools", "#a78bfa", "🤖"),
    "hustle": ("Side Hustles", "#ff7849", "⚡"),
    "freelanc": ("Side Hustles", "#ff7849", "⚡"),
    "side": ("Side Hustles", "#ff7849", "⚡"),
}


def detect_category(filename: str, title: str) -> tuple:
    text = (filename + " " + title).lower()
    for key, cat in CATEGORY_MAP.items():
        if key in text:
            return cat
    return ("Finance", "#6b7694", "📊")


def parse_post(html_path: Path) -> dict:
    html = html_path.read_text(encoding="utf-8", errors="ignore")

    # Title
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    title = m.group(1).strip() if m else html_path.stem.replace("-", " ").title()

    # Description
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.I)
    description = m.group(1).strip() if m else ""

    # Date from filename prefix YYYYMMDD
    m = re.match(r"(\d{4})(\d{2})(\d{2})-", html_path.name)
    if m:
        date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_display = datetime.now().strftime("%B %d, %Y")

    cat_name, cat_color, cat_icon = detect_category(html_path.name, title)

    return {
        "file": html_path.name,
        "url": f"/blog/{html_path.name}",
        "title": title,
        "description": description[:180] + ("..." if len(description) > 180 else ""),
        "date": date_str,
        "date_display": date_display,
        "category": cat_name,
        "cat_color": cat_color,
        "cat_icon": cat_icon,
    }


def build_card(p: dict) -> str:
    return f"""
    <article class="post-card" data-cat="{p['category']}">
      <div class="card-cat" style="color:{p['cat_color']};border-color:{p['cat_color']}30">
        {p['cat_icon']} {p['category']}
      </div>
      <h2 class="card-title"><a href="{p['url']}">{p['title']}</a></h2>
      <p class="card-desc">{p['description']}</p>
      <div class="card-footer">
        <span class="card-date">{p['date_display']}</span>
        <a href="{p['url']}" class="card-read">Read →</a>
      </div>
    </article>"""


def build_index(posts: list) -> str:
    cards_html = "\n".join(build_card(p) for p in posts)
    categories = sorted(set(p["category"] for p in posts))
    filter_btns = '<button class="filter-btn active" data-filter="all">All</button>\n'
    filter_btns += "\n".join(
        f'<button class="filter-btn" data-filter="{c}">{c}</button>'
        for c in categories
    )
    total = len(posts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blog — WheellsVerse | Daily AI + Money Insights</title>
<meta name="description" content="Daily articles on crypto, stocks, passive income, AI tools, and side hustles. New content every morning. Real strategies, honest numbers.">
<meta property="og:title" content="WheellsVerse Blog — Daily Money & AI Insights">
<meta property="og:description" content="Fresh guides on crypto, stocks, passive income, AI tools, and side hustles — published daily.">
<link rel="canonical" href="{SITE_URL}/blog/">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#080b11;--surface:#0f1320;--card:#141825;--border:#1e2435;
      --cyan:#00d4ff;--green:#00ff88;--gold:#ffd700;--text:#e0e6f0;--muted:#6b7694}}
html{{scroll-behavior:smooth}}
body{{font-family:'Inter','Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--text);
      line-height:1.6;-webkit-font-smoothing:antialiased}}

/* Nav */
nav{{position:fixed;top:0;width:100%;z-index:100;background:rgba(8,11,17,.95);
     border-bottom:1px solid var(--border);backdrop-filter:blur(12px);
     padding:14px 24px;display:flex;align-items:center;justify-content:space-between}}
.nav-logo{{font-size:1.1rem;font-weight:800;color:var(--text);text-decoration:none;display:flex;align-items:center;gap:8px}}
.nav-logo span{{color:var(--cyan)}}
.nav-links{{display:flex;gap:20px;align-items:center}}
.nav-links a{{color:var(--muted);text-decoration:none;font-size:14px;font-weight:500;transition:color .2s}}
.nav-links a:hover,.nav-links a.active{{color:var(--cyan)}}
.nav-cta{{background:var(--cyan);color:#000;border:none;padding:8px 20px;border-radius:6px;
          font-weight:700;font-size:13px;cursor:pointer;text-decoration:none;transition:opacity .2s}}
.nav-cta:hover{{opacity:.85}}

/* Hero */
.blog-hero{{padding:120px 24px 60px;text-align:center;
            background:radial-gradient(ellipse at 60% 0%,rgba(0,212,255,.07) 0%,transparent 60%),var(--bg)}}
.blog-hero h1{{font-size:clamp(1.8rem,4vw,2.8rem);font-weight:900;margin-bottom:14px}}
.blog-hero h1 em{{font-style:normal;color:var(--cyan)}}
.blog-hero p{{color:var(--muted);font-size:1rem;max-width:500px;margin:0 auto 32px}}
.post-count{{display:inline-block;background:rgba(0,212,255,.1);color:var(--cyan);
             border:1px solid rgba(0,212,255,.25);border-radius:20px;
             padding:4px 14px;font-size:12px;font-weight:700;margin-bottom:20px}}

/* Filter */
.filters{{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-bottom:0}}
.filter-btn{{background:var(--surface);border:1px solid var(--border);color:var(--muted);
             border-radius:20px;padding:6px 16px;font-size:13px;font-weight:600;
             cursor:pointer;transition:all .2s}}
.filter-btn:hover{{border-color:var(--cyan);color:var(--cyan)}}
.filter-btn.active{{background:rgba(0,212,255,.12);border-color:rgba(0,212,255,.4);color:var(--cyan)}}

/* Grid */
.blog-section{{padding:60px 24px 80px;max-width:1100px;margin:0 auto}}
.blog-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:24px}}

/* Card */
.post-card{{background:var(--card);border:1px solid var(--border);border-radius:14px;
            padding:24px;display:flex;flex-direction:column;gap:12px;
            transition:border-color .2s,transform .2s}}
.post-card:hover{{border-color:rgba(0,212,255,.3);transform:translateY(-2px)}}
.card-cat{{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:700;
           letter-spacing:1px;text-transform:uppercase;border:1px solid;
           border-radius:20px;padding:3px 10px;width:fit-content}}
.card-title{{font-size:1.05rem;font-weight:700;line-height:1.4;flex:1}}
.card-title a{{color:var(--text);text-decoration:none;transition:color .2s}}
.card-title a:hover{{color:var(--cyan)}}
.card-desc{{font-size:13px;color:var(--muted);line-height:1.6}}
.card-footer{{display:flex;align-items:center;justify-content:space-between;margin-top:auto;padding-top:8px;border-top:1px solid var(--border)}}
.card-date{{font-size:12px;color:var(--muted)}}
.card-read{{font-size:13px;font-weight:700;color:var(--cyan);text-decoration:none;transition:opacity .2s}}
.card-read:hover{{opacity:.75}}
.post-card.hidden{{display:none}}

/* CTA */
.cta-bar{{background:linear-gradient(135deg,rgba(0,212,255,.07),rgba(124,58,237,.07));
          border-top:1px solid var(--border);border-bottom:1px solid var(--border);
          padding:60px 24px;text-align:center}}
.cta-bar h2{{font-size:clamp(1.4rem,3vw,2rem);font-weight:800;margin-bottom:12px}}
.cta-bar p{{color:var(--muted);max-width:460px;margin:0 auto 28px}}
.cta-form{{display:flex;gap:10px;max-width:420px;margin:0 auto;flex-wrap:wrap;justify-content:center}}
.cta-form input{{flex:1;min-width:200px;padding:12px 16px;background:var(--surface);
                  border:1px solid var(--border);border-radius:8px;color:var(--text);
                  font-size:14px;outline:none;transition:border-color .2s}}
.cta-form input:focus{{border-color:var(--cyan)}}
.cta-form input::placeholder{{color:var(--muted)}}
.cta-form button{{padding:12px 24px;background:var(--cyan);color:#000;border:none;
                   border-radius:8px;font-weight:800;font-size:14px;cursor:pointer;
                   transition:opacity .2s;white-space:nowrap}}
.cta-form button:hover{{opacity:.85}}
.cta-fine{{font-size:11px;color:var(--muted);margin-top:10px}}
.cta-success{{color:var(--green);font-weight:700;font-size:1rem;margin-top:12px;display:none}}

/* Affiliate */
.aff-bar{{padding:40px 24px;max-width:1100px;margin:0 auto}}
.aff-bar-inner{{background:var(--surface);border:1px solid var(--border);border-radius:14px;
                padding:24px 28px;display:flex;align-items:center;gap:24px;flex-wrap:wrap}}
.aff-bar p{{color:var(--muted);font-size:13px;flex:1;min-width:200px}}
.aff-links{{display:flex;gap:10px;flex-wrap:wrap}}
.aff-link{{padding:9px 18px;border-radius:8px;font-size:13px;font-weight:700;
           text-decoration:none;transition:opacity .2s;white-space:nowrap}}
.aff-link:hover{{opacity:.82}}
.aff-link--cyan{{background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.3);color:var(--cyan)}}
.aff-link--green{{background:rgba(0,255,136,.1);border:1px solid rgba(0,255,136,.25);color:var(--green)}}
.aff-link--gold{{background:rgba(255,215,0,.08);border:1px solid rgba(255,215,0,.2);color:var(--gold)}}

/* Footer */
footer{{background:var(--surface);border-top:1px solid var(--border);
        padding:28px 24px;text-align:center;font-size:12px;color:var(--muted)}}
footer a{{color:var(--cyan);text-decoration:none}}

@media(max-width:640px){{
  .blog-hero{{padding:100px 16px 48px}}
  .blog-section{{padding:40px 16px 60px}}
  .aff-bar-inner{{flex-direction:column}}
}}
</style>
</head>
<body>

<nav>
  <a href="/" class="nav-logo">Wheells<span>Verse</span></a>
  <div class="nav-links">
    <a href="/blog/" class="active">Blog</a>
    <a href="/#earn">Earn</a>
    <a href="/#join" class="nav-cta">Free Signals</a>
  </div>
</nav>

<div class="blog-hero">
  <div class="post-count">{total} Articles Published</div>
  <h1>Daily <em>Money & AI</em> Insights</h1>
  <p>Guides on crypto, stocks, passive income, AI tools, and side hustles — published every morning.</p>
  <div class="filters">
    {filter_btns}
  </div>
</div>

<section class="blog-section">
  <div class="blog-grid" id="grid">
    {cards_html}
  </div>
</section>

<!-- Affiliate bar -->
<div class="aff-bar">
  <div class="aff-bar-inner">
    <p><strong style="color:var(--text)">Recommended picks from today's articles:</strong><br>
    All links below are affiliate links — we earn a commission at no cost to you.</p>
    <div class="aff-links">
      <a href="https://app.wheellsverse.com/go/robinhood" target="_blank" class="aff-link aff-link--cyan">📈 Free Stock — Robinhood</a>
      <a href="https://app.wheellsverse.com/go/coinbase" target="_blank" class="aff-link aff-link--green">₿ $10 BTC — Coinbase</a>
      <a href="https://www.amazon.com/s?k=passive+income+investing&tag=wheellsverse-20" target="_blank" class="aff-link aff-link--gold">📚 Best Books — Amazon</a>
    </div>
  </div>
</div>

<!-- Newsletter CTA -->
<div class="cta-bar">
  <h2>Get These Articles in Your Inbox</h2>
  <p>Daily signals on crypto, stocks, and AI money strategies. Free. One email per day.</p>
  <form class="cta-form" id="blog-subscribe-form">
    <input type="email" placeholder="your@email.com" required id="blog-email">
    <button type="submit" id="blog-sub-btn">Subscribe Free →</button>
  </form>
  <p class="cta-fine">No spam. Unsubscribe anytime.</p>
  <p class="cta-success" id="blog-success">✓ You're subscribed! Check your inbox.</p>
</div>

<footer>
  <p>&copy; 2026 WheellsVerse by J.K. Blaze &nbsp;·&nbsp;
     <a href="/">Home</a> &nbsp;·&nbsp;
     <a href="/blog/">Blog</a> &nbsp;·&nbsp;
     <a href="/#earn">Earn</a>
  </p>
  <p style="margin-top:8px;font-size:11px;color:#3a4260">
    Content is AI-generated for informational purposes only. Not financial advice. Do your own research.
  </p>
</footer>

<script>
// Category filter
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const f = btn.dataset.filter;
    document.querySelectorAll('.post-card').forEach(card => {{
      card.classList.toggle('hidden', f !== 'all' && card.dataset.cat !== f);
    }});
  }});
}});

// Newsletter form → Railway backend
document.getElementById('blog-subscribe-form').addEventListener('submit', async e => {{
  e.preventDefault();
  const email = document.getElementById('blog-email').value.trim();
  const btn   = document.getElementById('blog-sub-btn');
  btn.textContent = 'Joining...';
  btn.disabled = true;
  try {{
    await fetch('https://grateful-flexibility-production.up.railway.app/api/lead', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{email, name:'', source:'blog_index', topic:'Money & AI'}}),
    }});
  }} catch(err) {{}}
  document.getElementById('blog-success').style.display = 'block';
  document.getElementById('blog-subscribe-form').style.display = 'none';
}});
</script>
</body>
</html>"""


def build_sitemap(posts: list) -> str:
    now = datetime.now().strftime("%Y-%m-%d")
    urls = [
        f"  <url><loc>{SITE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority><lastmod>{now}</lastmod></url>",
        f"  <url><loc>{SITE_URL}/blog/</loc><changefreq>daily</changefreq><priority>0.9</priority><lastmod>{now}</lastmod></url>",
    ]
    for p in posts:
        urls.append(
            f"  <url><loc>{SITE_URL}{p['url']}</loc>"
            f"<changefreq>weekly</changefreq><priority>0.8</priority>"
            f"<lastmod>{p['date']}</lastmod></url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )


def main():
    BLOG_DIR.mkdir(parents=True, exist_ok=True)

    html_files = sorted(
        [f for f in BLOG_DIR.glob("*.html") if f.name != "index.html"],
        key=lambda x: x.name,
        reverse=True,   # newest first
    )

    if not html_files:
        print("No blog posts found — nothing to generate")
        return

    posts = [parse_post(f) for f in html_files]
    print(f"Found {len(posts)} posts")

    # Write blog index
    index_path = BLOG_DIR / "index.html"
    index_path.write_text(build_index(posts), encoding="utf-8")
    print(f"Blog index → {index_path}")

    # Write sitemap
    sitemap_path = ROOT / "frontend" / "sitemap.xml"
    sitemap_path.write_text(build_sitemap(posts), encoding="utf-8")
    print(f"Sitemap    → {sitemap_path}")


if __name__ == "__main__":
    main()
