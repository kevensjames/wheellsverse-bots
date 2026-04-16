#!/usr/bin/env python3
"""
Amazon KDP Automated Uploader
Uses Playwright to log into KDP and publish books automatically.
Also generates covers via DALL-E 3.

Requires in .env:
  KDP_EMAIL=your@email.com
  KDP_PASSWORD=yourpassword
  OPENAI_API_KEY=sk-...  (already set — used for cover generation)
"""
import base64
import json
import os
import time
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("kdp_uploader")


class SeriesGuardError(Exception):
    """Raised when a sequel is uploaded before its predecessor is live on KDP."""
    pass


def _check_series_guard(title: str, series: str = "", volume: int = 0):
    """
    Raise SeriesGuardError if volume > 1 and Vol N-1 is not live in the KDP registry.
    Parses 'Volume 2', 'Vol. 2', 'Book 2' from title if volume not explicitly given.
    """
    import re as _re
    if not volume:
        m = _re.search(r'\b(?:Volume|Vol\.?|Book)\s*(\d+)', title, _re.IGNORECASE)
        volume = int(m.group(1)) if m else 0
    if not volume or volume <= 1:
        return  # standalone or Vol 1 — no guard needed

    # Try to infer series name from title if not provided
    if not series:
        m = _re.search(r'^(.*?)\s*(?:Volume|Vol\.?|Book)\s*\d+', title, _re.IGNORECASE)
        series = m.group(1).strip(': -').strip() if m else title

    if not series:
        return

    from core.kdp_registry import get_registry
    reg = get_registry()
    prev_vol = volume - 1

    if not reg.series_exists_on_kdp(series, prev_vol):
        raise SeriesGuardError(
            f"SERIES GUARD: Cannot upload '{title}' (Volume {volume}) — "
            f"'{series} Volume {prev_vol}' is not yet live on KDP. "
            f"Publish Volume {prev_vol} first, then retry."
        )


# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
COVERS_DIR = ROOT / "outputs" / "books" / "covers" / "generated"
COVERS_DIR.mkdir(parents=True, exist_ok=True)

KDP_URL = "https://kdp.amazon.com"
KDP_LOGIN_URL = "https://kdp.amazon.com/en_US/"


def generate_cover(title: str, genre: str, dall_e_prompt: str = None) -> Path:
    """Generate book cover via DALL-E 3, save as JPG. Returns path."""
    import openai

    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    genre_styles = {
        "childrens": (
            "Magical children's book cover illustration. Adorable cartoon characters in a vibrant enchanted world. "
            "Lush watercolor painting style with soft glowing light, pastel rainbow palette, whimsical clouds and stars. "
            "A brave little hero on a grand adventure — wide eyes, colorful animals, sparkling magic. "
            "Pixar-quality 3D render meets hand-painted storybook art. Warm, joyful, instantly lovable."
        ),
        "mystery": (
            "Cinematic noir mystery book cover. A lone detective silhouette stands beneath a glowing streetlamp in heavy rain, "
            "long coat, fedora, the city reflected in dark wet cobblestones behind them. Deep shadows, high contrast. "
            "Moody amber and midnight blue palette. Fog curling around art deco buildings. "
            "Photorealistic oil painting style. Dramatic, tense, irresistibly intriguing."
        ),
        "adventure": (
            "Epic adventure book cover. A lone explorer at the edge of a vast lost jungle canyon, golden temples visible through mist. "
            "Dramatic golden-hour lighting, sweeping cinematic landscape. Lush emerald greens, deep canyon shadows, warm sunset glow. "
            "Hyper-detailed concept art style, painterly realism. High contrast, rich color, sense of vast scale and danger. "
            "The kind of cover that makes you need to open the book immediately."
        ),
        "historical": (
            "Stunning historical fiction book cover. Grand classical oil painting style — baroque lighting, rich jewel tones. "
            "An important moment frozen in time: ornate period costumes, candlelit palace interior or dramatic battlefield. "
            "Masterwork brushwork, museum-quality composition. Deep reds, gold, ivory. "
            "Feels like a famous painting hanging in the Louvre. Majestic and timeless."
        ),
        "self_help": (
            "Bold modern self-help book cover. Striking minimalist design — a single powerful symbolic image: "
            "a person breaking through a wall of light, a mountain summit at sunrise, or a butterfly emerging. "
            "Clean geometric composition. Vibrant gradient background — electric blue to gold or deep purple to orange. "
            "High-end graphic design aesthetic. Inspirational, energizing, visually arresting."
        ),
        "romance": (
            "Gorgeous romance novel cover. Two figures caught in a breathless moment — almost touching, longing in their eyes. "
            "Soft golden-hour light filtering through, warm bokeh background. Elegant, sensual composition. "
            "Rich rose gold and champagne palette with deep shadow accents. "
            "Painterly realism meets fashion photography. Emotionally charged, beautiful, unforgettable."
        ),
        "sci_fi": (
            "Stunning science fiction book cover. A vast alien world or space station seen from orbit, rings of a gas giant filling the sky. "
            "A lone astronaut or starship in the foreground for scale. Neon blues, purples, and electric cyan against deep black space. "
            "Hyper-detailed digital painting, cinematic composition like a movie poster. "
            "Awe-inspiring scale, cutting-edge futuristic aesthetic, sense of infinite wonder."
        ),
        "fantasy": (
            "Epic high fantasy book cover. A mighty dragon soaring over an ancient sorcerer's tower as lightning strikes, "
            "a chosen hero below with a glowing magical sword. Breathtaking mountain landscape at twilight. "
            "Deep purples, molten gold, and electric blue magical energy swirling. "
            "Fantasy concept art at its finest — dramatic, mythic, impossibly detailed. "
            "The kind of cover that transports you to another world."
        ),
        "horror": (
            "Terrifying horror book cover. A decaying Victorian mansion at midnight, single lit window, dark figure watching from inside. "
            "Blood moon casting red light across dead trees. Thick fog, absolute silence you can feel. "
            "Extreme atmospheric tension. Desaturated palette with deep crimson accents. "
            "Photorealistic horror movie poster quality. Deeply unsettling, impossible to look away, haunts you after."
        ),
        "true_crime": (
            "Gripping true crime book cover. Dark documentary aesthetic — a central mystery photograph, "
            "crime scene tape, shadowy figure, newspaper clippings layered in the background. "
            "High contrast black, white and deep red palette. Gritty realism, investigative journalism feel. "
            "Stark, urgent composition. The visual equivalent of a case file that blows open a cold case."
        ),
    }

    style = genre_styles.get(genre, "professional book cover, dramatic lighting, high quality publishable artwork")
    prompt = dall_e_prompt or (
        f"Professional Amazon Kindle book cover artwork. Genre: {genre}. "
        f"{style} "
        f"Ultra high quality, commercially publishable. Absolutely NO text, NO words, NO letters, NO numbers anywhere in the image. "
        f"Pure visual artwork only. 1:1 square format optimized for digital book stores."
    )

    logger.info("Generating cover for: %s (%s)", title, genre)

    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="hd",
        n=1,
        response_format="b64_json",
    )

    img_data = base64.b64decode(response.data[0].b64_json)
    safe_title = title.lower().replace(" ", "_").replace("'", "")[:30]
    cover_path = COVERS_DIR / f"cover_{genre}_{safe_title}.jpg"
    cover_path.write_bytes(img_data)
    logger.info("Cover saved: %s", cover_path)
    return cover_path


def _read_kdp_package(genre: str) -> dict:
    """Parse the KDP package markdown file for a given genre."""
    pub_dir = ROOT / "outputs" / "books" / "published"
    packages = list(pub_dir.glob(f"{genre}_*_kdp_package.md"))
    if not packages:
        return {}

    content = packages[-1].read_text(encoding="utf-8")
    data = {}

    # Extract fields with simple parsing
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if "**Book Title:**" in line or "**BOOK TITLE:**" in line:
            data["title"] = line.split(":", 1)[-1].strip().strip("*").strip()
        elif "**Subtitle:**" in line:
            data["subtitle"] = line.split(":", 1)[-1].strip().strip("*").strip()
        elif "**Series:**" in line:
            data["series"] = line.split(":", 1)[-1].strip().strip("*").strip()
        elif "**Author:**" in line or "**AUTHOR:**" in line:
            data["author"] = line.split(":", 1)[-1].strip().strip("*").strip()

    # Extract description block
    desc_start = content.find("<p>")
    desc_end = content.rfind("</p>") + 4
    if desc_start > -1 and desc_end > desc_start:
        data["description_html"] = content[desc_start:desc_end]

    # Extract keywords
    kw_section = content.find("KEYWORDS")
    if kw_section > -1:
        kw_lines = content[kw_section:kw_section + 500].split("\n")[1:8]
        data["keywords"] = [
            line.strip().lstrip("1234567890. ").strip()
            for line in kw_lines if line.strip() and line.strip()[0].isdigit()
        ][:7]

    return data


def _kdp_error(code: str, detail: str = "") -> dict:
    """Return a standardised error dict with a human-readable message."""
    messages = {
        "no_credentials": "KDP_EMAIL / KDP_PASSWORD missing in .env — add them and retry.",
        "no_manuscript": "No manuscript file found for this genre — run the book writer first.",
        "validation_failed": "Pre-submission validation failed — see 'validation_errors' for details.",
        "login_failed": "Amazon login failed — check your email/password in .env.",
        "2fa_timeout": "Two-factor authentication required — enter the code within 90s or disable 2FA.",
        "account_limit": "Amazon title creation limit reached — wait for pending books to be approved (24–72h).",
        "details_rejected": "KDP rejected the book details form — see screenshot for the specific error message.",
        "manuscript_upload": "Manuscript upload failed — KDP may not support this file format.",
        "cover_upload": "Cover image upload failed — ensure it's JPEG/PNG, under 50 MB, min 625×1000px.",
        "pricing_error": "KDP pricing/territory step failed — price must be $0.99–$9.99.",
        "publish_failed": "Final publish step failed — book may be saved as draft; check KDP dashboard.",
        "timeout": "Browser timed out waiting for KDP — Amazon may be slow; retry in a few minutes.",
        "unknown": "Unexpected error during KDP upload.",
    }
    msg = messages.get(code, messages["unknown"])
    if detail:
        msg = f"{msg} Detail: {detail}"
    logger.error("KDP error [%s]: %s", code, msg)
    return {"status": "error", "error_code": code, "error": msg}


def upload_book(genre: str, manuscript_path: str = None, cover_path: str = None,
                headless: bool = False) -> dict:
    """
    Full KDP upload automation via Playwright.
    Validates first, then logs in, fills all fields, uploads files, sets price, publishes.
    Logs all errors with descriptive messages. Retries transient failures automatically.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    email = os.getenv("KDP_EMAIL", "")
    password = os.getenv("KDP_PASSWORD", "")

    if not email or not password:
        return _kdp_error("no_credentials")

    # Find manuscript if not provided
    if not manuscript_path:
        genre_dir = ROOT / "outputs" / "books" / genre
        # Prefer files starting with "book_" (primary manuscripts), then fallback to others
        if genre_dir.exists():
            all_mds = list(genre_dir.glob("*.md"))
            # Exclude metadata/helper files (outlines, cover briefs, kdp packages, series notes)
            excluded = ("outline_", "cover_", "kdp_", "series_")
            book_files = sorted(
                [f for f in all_mds if f.name.startswith("book_")],
                key=lambda f: f.stat().st_mtime, reverse=True
            )
            other_files = sorted(
                [f for f in all_mds if not any(f.name.startswith(p) for p in excluded) and not f.name.startswith("book_")],
                key=lambda f: f.stat().st_mtime, reverse=True
            )
            # Pick the longest book_ file (most complete), fall back to others
            if book_files:
                # Among book_ files, prefer the one with most words (most complete)
                best = max(book_files, key=lambda f: len(f.read_text(errors="replace").split()))
                manuscripts = [best]
            else:
                manuscripts = other_files
        else:
            manuscripts = []
        if not manuscripts:
            return _kdp_error("no_manuscript", f"genre={genre}, looked in: {genre_dir}")
        manuscript_path = str(manuscripts[0])
        logger.info("Using manuscript: %s", manuscript_path)

    # Auto-upgrade .md → .html: KDP doesn't accept Markdown, prefer packaged HTML
    if manuscript_path and manuscript_path.endswith(".md"):
        stem = Path(manuscript_path).stem  # e.g. "pe_the_cartographer_of_dying_cities_20260412_230347"
        # Strip "pe_" prefix if present, as packaged HTMLs use the title slug
        html_stem = stem.lstrip("pe_").lstrip("bs_")
        packaged_dir = ROOT / "outputs" / "books" / "packaged"
        candidates = list(packaged_dir.glob(f"*{html_stem}*.html")) if packaged_dir.exists() else []
        if not candidates:
            # Broader search: any HTML in packaged dir matching key title words
            title_words = [w for w in html_stem.split("_") if len(w) > 3][:4]
            candidates = [f for f in packaged_dir.glob("*.html")
                          if all(w in f.stem for w in title_words)] if packaged_dir.exists() else []
        if candidates:
            manuscript_path = str(sorted(candidates, key=lambda f: f.stat().st_mtime, reverse=True)[0])
            logger.info("Auto-upgraded manuscript to HTML: %s", manuscript_path)

    # Read KDP package data
    pkg = _read_kdp_package(genre)
    title = pkg.get("title") or Path(manuscript_path).stem.replace("_", " ").title()[:60]
    author = pkg.get("author", "J.K. Blaze")
    description = pkg.get("description_html", f"A compelling {genre} novel by J.K. Blaze.")
    keywords = pkg.get("keywords", [f"{genre} fiction", "WheellsVerse"])

    # ── Series guard — block Vol N upload if Vol N-1 not live ────────────────
    try:
        _check_series_guard(
            title=title,
            series=pkg.get("series_name", ""),
            volume=int(pkg.get("volume_number") or 0),
        )
    except SeriesGuardError as _sg:
        logger.error("Series guard blocked upload: %s", _sg)
        return {"status": "error", "error_code": "series_guard",
                "error": str(_sg), "blocked": True}

    # ── Manuscript completeness gate ─────────────────────────────────────────
    ms_path_for_check = manuscript_path or pkg.get("manuscript_path", "")
    if ms_path_for_check:
        try:
            from pathlib import Path as _Path
            _ms_text = _Path(ms_path_for_check).read_text(encoding="utf-8", errors="replace")
            _tail    = _ms_text[-400:].lower()
            _end_markers = ["the end", "epilogue", "about the author", "acknowledgment"]
            _has_end = any(m in _tail for m in _end_markers)
            _last_char = _ms_text.rstrip()[-1:] if _ms_text.rstrip() else ""
            _wc = len(_ms_text.split())
            if _wc < 8000 or (not _has_end and _last_char not in (".", "!", "?", '"', "'", chr(8230))):
                logger.error(
                    "KDP upload blocked: manuscript incomplete (wc=%d, has_end=%s)", _wc, _has_end
                )
                return {
                    "status":     "error",
                    "error_code": "manuscript_incomplete",
                    "error":      f"Manuscript incomplete ({_wc} words, no end marker) — QC must pass first.",
                    "blocked":    True,
                }
        except FileNotFoundError:
            pass  # No file to check — let upload proceed
        except Exception as _ce:
            logger.warning("Manuscript completeness check failed (non-fatal): %s", _ce)

    # Price by genre
    from bots.books.book_publisher import KDP_PRICES
    price = KDP_PRICES.get(genre, 2.99)

    # Generate cover if not provided
    if not cover_path:
        try:
            cover_file = generate_cover(title, genre)
            cover_path = str(cover_file)
            logger.info("Cover generated: %s", cover_path)
        except Exception as e:
            logger.warning("Cover generation failed: %s — will use KDP cover creator", e)
            cover_path = None

    # Convert markdown to plain text for upload (KDP accepts .txt or .docx)
    txt_path = Path(manuscript_path).with_suffix(".txt")
    if not txt_path.exists():
        raw = Path(manuscript_path).read_text(encoding="utf-8")
        # Clean markdown syntax
        clean = "\n".join(
            line.lstrip("#").strip() if line.startswith("#") else line
            for line in raw.split("\n")
        )
        txt_path.write_text(clean, encoding="utf-8")

    # ── Pre-submission validation ─────────────────────────────────────────────
    try:
        from core.kdp_validator import KDPValidator
        vr = KDPValidator().validate(
            genre=genre,
            manuscript_path=manuscript_path,
            cover_path=cover_path,
            title=title,
            author=author,
            description=description,
            keywords=keywords,
            price=price,
        )
        if not vr.is_valid:
            err_summary = " | ".join(vr.errors[:5])
            logger.error("KDP validation failed for '%s': %s", title, err_summary)
            return {
                **_kdp_error("validation_failed"),
                "genre": genre,
                "title": title,
                "validation_errors": vr.errors,
                "validation_warnings": vr.warnings,
            }
        if vr.warnings:
            logger.warning("KDP validation warnings for '%s': %s", title, vr.warnings)
    except ImportError:
        logger.warning("kdp_validator not available — skipping pre-flight check")

    result = {
        "status": "pending",
        "genre": genre,
        "title": title,
        "manuscript": manuscript_path,
        "cover": cover_path,
        "price": price,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            slow_mo=300,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-web-security",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )
        # Hide webdriver flag
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        page.set_default_timeout(60000)

        try:
            # ── STEP 1: Go to KDP homepage then click Sign In ───────────────
            logger.info("Navigating to KDP...")
            try:
                page.goto(KDP_LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                # Fallback: commit means just start navigation, don't wait for full load
                page.goto(KDP_LOGIN_URL, wait_until="commit", timeout=45000)
            time.sleep(5)

            # Click "Sign In" if on the KDP landing page
            if "kdp.amazon.com" in page.url and "signin" not in page.url:
                logger.info("On KDP landing page — clicking Sign In...")
                try:
                    page.locator("a:has-text('Sign in'), a[href*='signin']").first.click()
                    page.wait_for_load_state("domcontentloaded")
                    time.sleep(3)
                except Exception as e:
                    logger.warning("Sign in click failed: %s — navigating directly", e)
                    page.goto("https://www.amazon.com/ap/signin?openid.return_to=https://kdp.amazon.com",
                              wait_until="domcontentloaded")
                    time.sleep(3)

            # ── STEP 2: Login ────────────────────────────────────────────────
            if "signin" in page.url or "ap/signin" in page.url or "amazon.com" in page.url:
                logger.info("Amazon sign-in page detected. Logging in...")
                page.set_default_timeout(30000)

                # Fill email (may already be pre-filled on KDP's own login page)
                try:
                    email_field = page.locator("#ap_email, input[type='email'], input[name='email']").first
                    if email_field.is_visible(timeout=10000):
                        email_field.fill(email)
                        time.sleep(0.5)
                        # Click Continue if separate step
                        try:
                            page.locator("#continue, button:has-text('Continue')").first.click()
                            time.sleep(2)
                        except Exception:
                            pass
                except Exception:
                    pass  # Email may already be filled (KDP remembers it)

                # Fill password — try multiple selectors (KDP uses different IDs)
                time.sleep(1)
                pw_filled = False
                for pw_sel in ["#ap_password", 'input[type="password"]', 'input[name="password"]']:
                    try:
                        pw_field = page.locator(pw_sel).first
                        if pw_field.is_visible(timeout=8000):
                            pw_field.fill(password)
                            pw_filled = True
                            logger.info("Password filled using selector: %s", pw_sel)
                            break
                    except Exception:
                        continue

                if not pw_filled:
                    logger.warning("Could not find password field — may already be logged in")

                # Click Sign In button
                time.sleep(0.5)
                for signin_sel in ["#signInSubmit", 'button[type="submit"]',
                                   'input[type="submit"]', 'button:has-text("Sign in")',
                                   'button:has-text("Sign In")']:
                    try:
                        btn = page.locator(signin_sel).first
                        if btn.is_visible(timeout=5000):
                            btn.click()
                            logger.info("Sign in clicked via: %s", signin_sel)
                            break
                    except Exception:
                        continue

                # Screenshot immediately after sign-in click (before waiting for redirect)
                time.sleep(5)
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_after_signin.png"))
                logger.info("After signin URL: %s", page.url)

                # Wait for redirect back to KDP (Amazon can take 60-120s)
                if "kdp.amazon.com" not in page.url:
                    try:
                        page.wait_for_url("*kdp.amazon.com*", timeout=120000)
                        logger.info("Redirected to KDP successfully")
                    except Exception:
                        logger.warning("Redirect wait timed out — URL: %s", page.url)
                        page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_signin_timeout.png"))
                time.sleep(3)

                # Handle OTP / 2FA
                if "auth-mfa" in page.url or "cvf" in page.url or "ap/cvf" in page.url:
                    logger.warning("⚠️  2FA/OTP required — waiting 90s for manual entry...")
                    print("\n⚠️  Amazon is asking for a verification code.")
                    print("Please enter the code in the browser window within 90 seconds.\n")
                    try:
                        page.wait_for_url("*kdp.amazon.com*", timeout=90000)
                    except Exception:
                        pass

            logger.info("Logged in. URL: %s", page.url)

            # ── STEP 3: Navigate to 'Create New Title' ───────────────────────
            page.set_default_timeout(60000)

            def click_and_wait(selectors, action_name, timeout_each=5000):
                for sel in selectors:
                    try:
                        loc = page.locator(sel).first
                        if loc.is_visible(timeout=timeout_each):
                            loc.click()
                            page.wait_for_load_state("domcontentloaded", timeout=30000)
                            logger.info("%s via '%s' — URL: %s", action_name, sel, page.url)
                            return True
                    except Exception:
                        continue
                return False

            # ── Helper: detect + dismiss Amazon limit popup ──────────────────
            def _dismiss_any_popup() -> str:
                """
                Check for any blocking KDP modal and dismiss it.
                Returns the modal text if found, empty string if none.
                """
                try:
                    modal_text = page.evaluate("""() => {
                        const selectors = [
                            '[role="dialog"]', '[role="alertdialog"]',
                            '.a-popover-wrapper', '.a-modal-wrapper',
                            'div[class*="modal"]', 'div[class*="dialog"]',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.offsetParent !== null) {
                                return el.textContent.trim().slice(0, 200);
                            }
                        }
                        return '';
                    }""")
                    if not modal_text:
                        return ''
                    logger.info("Popup detected: %s", modal_text[:100])
                    # Click dismiss button (Continue / OK / Close / Got it)
                    for dismiss_sel in [
                        "button:has-text('Continue')",
                        "button:has-text('OK')",
                        "button:has-text('Got it')",
                        "button:has-text('Close')",
                        "button:has-text('Dismiss')",
                        "[aria-label='Close']",
                        ".a-popover-closebutton",
                    ]:
                        try:
                            btn = page.locator(dismiss_sel).first
                            if btn.is_visible(timeout=2000):
                                btn.click()
                                time.sleep(2)
                                logger.info("Popup dismissed via '%s'", dismiss_sel)
                                return modal_text
                        except Exception:
                            continue
                    # Fallback: press Escape
                    page.keyboard.press("Escape")
                    time.sleep(2)
                    return modal_text
                except Exception as e:
                    logger.debug("_dismiss_any_popup error: %s", e)
                    return ''

            if "title/create" not in page.url:
                # Step 3a: From bookshelf, navigate to the create hub
                if "bookshelf" in page.url or "kdp.amazon.com" in page.url:
                    clicked = click_and_wait([
                        "a:has-text('+ Kindle eBook')",
                        "button:has-text('+ Kindle eBook')",
                        "a:has-text('Kindle eBook')",
                        "button:has-text('Kindle eBook')",
                    ], "Kindle eBook create button")

                    if not clicked:
                        # Try the general create hub
                        page.goto(f"{KDP_URL}/en_US/create", wait_until="domcontentloaded", timeout=45000)
                        time.sleep(3)
                        logger.info("Navigated to create hub: %s", page.url)

                # Step 3b: On the create hub (/create), click "Create ebook"
                if "title/create" not in page.url:
                    clicked = click_and_wait([
                        "button:has-text('Create ebook')",
                        "a:has-text('Create ebook')",
                        "button:has-text('Create eBook')",
                        "a:has-text('Create eBook')",
                        "button:has-text('Kindle eBook')",
                        "a:has-text('Kindle eBook')",
                        "a[href*='title/create']",
                    ], "Create ebook on create hub")

                    if not clicked:
                        logger.warning("Could not find Kindle eBook button — URL: %s", page.url)

                time.sleep(3)
                # Check for limit popup immediately after navigating to create page
                popup_txt = _dismiss_any_popup()
                if popup_txt and "limit" in popup_txt.lower():
                    page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_limit_popup.png"))
                    result.update(_kdp_error("account_limit"))
                    result["screenshot"] = str(ROOT / "outputs" / "books" / f"kdp_{genre}_limit_popup.png")
                    raise Exception("account_limit_reached")

                logger.info("After create navigation — URL: %s", page.url)
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_step3.png"))

            # ── STEP 5: Book Details ─────────────────────────────────────────
            logger.info("Filling book details... URL: %s", page.url)
            time.sleep(2)  # Let page fully load

            def safe_fill(selector, value, timeout=5000):
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=timeout):
                        el.fill(value)
                        # Fire events to satisfy React's synthetic event system
                        el.dispatch_event("input")
                        el.dispatch_event("change")
                        return True
                except Exception:
                    pass
                return False

            # Language
            try:
                page.select_option('select[name="data[language]"], select[id*="language"]', "en")
            except Exception:
                pass

            # Title — real KDP ID: data-title
            if not safe_fill('#data-title', title):
                safe_fill('input[name="data[title]"]', title)

            # Subtitle
            subtitle = pkg.get("subtitle", "")
            if subtitle:
                safe_fill('#data-subtitle', subtitle[:200])

            # Author — KDP has BOTH data[primary_author] and data[contributors][0] fields
            # Both must be filled; validation checks data[primary_author]
            def fill_author_field(sel, value):
                """Fill an author input and fire React-compatible events via nativeInputValueSetter."""
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        el.fill(value)
                        el.dispatch_event("input")
                        el.dispatch_event("change")
                        logger.info("Author field '%s' filled with '%s'", sel, value)
                        return True
                except Exception:
                    pass
                return False

            # Fill primary_author fields (what KDP validates)
            fill_author_field('#data-primary-author-first-name', "J.K.")
            fill_author_field('#data-primary-author-last-name', "Blaze")
            # Fill contributors[0] fields (visible editor row)
            fill_author_field('#data-contributors-0-first-name', "J.K.")
            fill_author_field('#data-contributors-0-last-name', "Blaze")

            # Description — scroll down to find it
            page.evaluate("window.scrollTo(0, 600)")
            time.sleep(2)
            desc_filled = False
            desc_text = description[:4000]
            # Strip HTML tags to plain text for the editor
            import re as _re
            desc_plain = _re.sub(r'<[^>]+>', ' ', desc_text).strip()[:2000]
            if not desc_plain:
                desc_plain = f"A gripping {genre} novel that will keep you on the edge of your seat from start to finish. Featuring complex characters, unexpected twists, and a richly detailed world, this book delivers an unforgettable reading experience."

            # Method 1: TinyMCE iframe (KDP's description editor lives in frame[1])
            # IMPORTANT: skip frames[0] — that is the main document, not the editor iframe!
            try:
                frames = page.frames
                logger.info("Page has %d frames: %s", len(frames),
                            [(f.url or "")[:60] for f in frames])
                # Only check non-main frames (skip index 0)
                for frame in frames[1:]:
                    furl = (frame.url or "").strip()
                    # TinyMCE iframes have about:blank, javascript:void, or tiny_mce URL
                    is_editor_frame = (
                        furl in ("about:blank", "javascript:void(0)", "javascript:\"\"", "") or
                        "tiny" in furl.lower() or
                        not furl.startswith("http")
                    )
                    logger.info("Checking frame: url='%s' is_editor=%s", furl, is_editor_frame)
                    if is_editor_frame:
                        try:
                            body = frame.locator("body")
                            body.wait_for(state="attached", timeout=5000)
                            body.click(timeout=5000)
                            time.sleep(0.3)
                            frame.evaluate("document.body.innerHTML = ''")
                            body.type(desc_plain[:1500], delay=0)
                            desc_filled = True
                            logger.info("Description filled via TinyMCE iframe (url='%s')", furl)
                            break
                        except Exception as fe:
                            logger.debug("Frame fill failed: %s", fe)
                            continue
            except Exception as e:
                logger.warning("Iframe description search failed: %s", e)

            if not desc_filled:
                # Method 2: Use frame_locator for named TinyMCE iframes
                try:
                    for fl_sel in [
                        'iframe[title*="description" i]',
                        'iframe[id*="description" i]',
                        'iframe[id*="tinymce" i]',
                        'iframe[class*="mce" i]',
                    ]:
                        try:
                            body = page.frame_locator(fl_sel).first.locator("body")
                            body.click(timeout=5000)
                            page.keyboard.press("Control+a")
                            page.keyboard.type(desc_plain[:1500], delay=0)
                            desc_filled = True
                            logger.info("Description filled via frame_locator '%s'", fl_sel)
                            break
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug("frame_locator attempt failed: %s", e)

            if not desc_filled:
                # Method 3: Plain textarea / input
                for desc_sel in [
                    '#data-book-description',
                    '#book-description',
                    'textarea[name="data[description]"]',
                    'textarea[id*="description" i]',
                ]:
                    try:
                        el = page.locator(desc_sel).first
                        if el.is_visible(timeout=3000):
                            el.click()
                            page.keyboard.press("Control+a")
                            el.fill(desc_plain)
                            el.dispatch_event("input")
                            el.dispatch_event("change")
                            desc_filled = True
                            logger.info("Description filled via textarea %s", desc_sel)
                            break
                    except Exception:
                        continue

            if not desc_filled:
                # Method 4: contenteditable div (React rich-text editor)
                try:
                    el = page.locator('div[contenteditable="true"]').first
                    if el.is_visible(timeout=5000):
                        el.scroll_into_view_if_needed()
                        el.click()
                        time.sleep(0.5)
                        page.keyboard.press("Control+a")
                        page.keyboard.press("Delete")
                        time.sleep(0.3)
                        page.keyboard.type(desc_plain[:1500], delay=0)
                        desc_filled = True
                        logger.info("Description filled via contenteditable keyboard.type")
                except Exception as e:
                    logger.warning("Description contenteditable fill failed: %s", e)

            if not desc_filled:
                logger.warning("Could not fill description — KDP will require manual entry")

            page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_desc_state.png"))
            logger.info("Description fill status: %s", desc_filled)

            # Keywords — real IDs: data-keyword-0 through data-keyword-6
            page.evaluate("window.scrollTo(0, 1200)")
            time.sleep(1)
            for i, kw in enumerate(keywords[:7]):
                filled = safe_fill(f'#data-keyword-{i}', kw[:50])
                if not filled:
                    safe_fill(f'input[name="data[keywords][{i}]"]', kw[:50])

            # Publishing Rights — "I own the copyright and hold necessary publishing rights"
            try:
                for rights_sel in [
                    'input[value="true"][name*="right"]',
                    'input[id*="own"][name*="right"]',
                    'input[id*="copyright"]',
                    "label:has-text('I own the copyright')",
                    "label:has-text('own the copyright')",
                ]:
                    try:
                        r = page.locator(rights_sel).first
                        if r.is_visible(timeout=3000):
                            r.click()
                            logger.info("Publishing rights selected via %s", rights_sel)
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            # Adult content: No — scroll to make it visible first
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
            time.sleep(1)
            adult_clicked = False
            try:
                for adult_sel in [
                    'input[value="false"][name*="adult"]',
                    'input[id*="no"][name*="adult"]',
                    "label:has-text('No, it does not')",
                    "label:has-text('not contain')",
                    "label:has-text('No')",
                ]:
                    try:
                        a = page.locator(adult_sel).first
                        if a.is_visible(timeout=2000):
                            a.click()
                            adult_clicked = True
                            logger.info("Adult content 'No' selected via %s", adult_sel)
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            if not adult_clicked:
                # JS fallback — click the "No" radio for adult content
                try:
                    adult_result = page.evaluate("""() => {
                        const radios = document.querySelectorAll('input[type="radio"]');
                        for (const r of radios) {
                            const lbl = document.querySelector('label[for="' + r.id + '"]');
                            const txt = (lbl ? lbl.textContent : r.value || '').toLowerCase();
                            if ((txt.includes('no') || r.value === 'false') && r.name && r.name.toLowerCase().includes('adult')) {
                                r.click();
                                return r.id || r.value;
                            }
                        }
                        return null;
                    }""")
                    if adult_result:
                        logger.info("Adult content 'No' selected via JS: %s", adult_result)
                except Exception as e:
                    logger.warning("Adult content selection failed: %s", e)

            # Categories — KDP requires at least one category before Save & Continue
            # Strategy: open modal -> select main category via a-dropdown -> select subcategory -> save
            # Retry up to 3 times if category validation error persists
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            time.sleep(2)

            genre_kdp_category = {
                "childrens": "Children's Books",
                "mystery": "Mystery",
                "adventure": "Action & Adventure",
                "historical": "Historical Fiction",
                "self_help": "Self-Help",
                "romance": "Romance",
                "sci_fi": "Science Fiction & Fantasy",
                "fantasy": "Science Fiction & Fantasy",
                "horror": "Horror",
                "true_crime": "True Crime",
            }
            # Sub-category keyword for the 2nd dropdown (more specific)
            genre_kdp_subcat = {
                "childrens": "children",
                "mystery": "mystery",
                "adventure": "adventure",
                "historical": "historical",
                "self_help": "self",
                "romance": "romance",
                "sci_fi": "science",
                "fantasy": "fantasy",
                "horror": "horror",
                "true_crime": "crime",
            }
            cat_keyword = genre_kdp_category.get(genre, "Literature")
            subcat_keyword = genre_kdp_subcat.get(genre, "")

            def _open_cat_modal():
                for cat_btn_sel in [
                    "button:has-text('Choose categories')",
                    "a:has-text('Choose categories')",
                    "button:has-text('Add a category')",
                    "a:has-text('Add a category')",
                    "[data-automation-id*='categories' i]",
                ]:
                    try:
                        btn = page.locator(cat_btn_sel).first
                        if btn.is_visible(timeout=5000):
                            btn.scroll_into_view_if_needed()
                            btn.click()
                            logger.info("Category modal opened: '%s'", cat_btn_sel)
                            return True
                    except Exception:
                        continue
                clicked = page.evaluate("""() => {
                    for (const el of document.querySelectorAll('button, a')) {
                        const t = (el.textContent || '').trim().toLowerCase();
                        if (t.includes('choose categor') || t.includes('add a categor')) {
                            el.scrollIntoView(); el.click(); return t;
                        }
                    }
                    return null;
                }""")
                if clicked:
                    logger.info("Category modal opened via JS: '%s'", clicked)
                    return True
                return False

            def _click_dropdown_option(kw, position="first"):
                triggers = page.locator('span.a-dropdown-prompt').all()
                if not triggers:
                    triggers = page.locator('span.a-button-text:has-text("Select one")').all()
                logger.info("Dropdown triggers found: %d", len(triggers))
                target = triggers[0] if (position == "first" and triggers) else (triggers[-1] if triggers else None)
                if not target:
                    return None
                try:
                    target.scroll_into_view_if_needed()
                    target.click(timeout=5000)
                    time.sleep(1.5)
                    page.wait_for_selector(
                        'ul.a-list-link li a, li.a-dropdown-item a, .a-dropdown-link',
                        state="visible", timeout=6000
                    )
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning("Dropdown trigger click failed: %s", e)
                    return None
                kw_lower = kw.lower()
                clicked = page.evaluate("""(kw) => {
                    const items = document.querySelectorAll(
                        'ul.a-list-link li a, li.a-dropdown-item a, .a-dropdown-link, ul[role=listbox] li a'
                    );
                    const visible = Array.from(items).filter(el => el.offsetParent !== null);
                    let t = kw ? visible.find(el => el.textContent.toLowerCase().includes(kw)) : null;
                    if (!t) t = visible.find(el => {
                        const txt = el.textContent.trim().toLowerCase();
                        return txt && txt !== 'select one';
                    });
                    if (t) { t.click(); return t.textContent.trim(); }
                    return null;
                }""", kw_lower)
                if clicked:
                    logger.info("Dropdown option clicked: '%s'", clicked)
                    time.sleep(2)
                return clicked

            def _save_cat_modal():
                for save_sel in [
                    "button:has-text('Save categories')",
                    "button:has-text('Add categories')",
                ]:
                    try:
                        btn = page.locator(save_sel).first
                        if btn.is_visible(timeout=5000):
                            btn.click()
                            logger.info("Category modal saved: '%s'", save_sel)
                            time.sleep(3)
                            return True
                    except Exception:
                        continue
                saved = page.evaluate("""() => {
                    for (const btn of document.querySelectorAll('button')) {
                        const t = (btn.textContent || '').trim();
                        if (t === 'Save categories' || t === 'Add categories' || t === 'Done') {
                            btn.click(); return t;
                        }
                    }
                    return null;
                }""")
                if saved:
                    logger.info("Category saved via JS: '%s'", saved)
                    time.sleep(3)
                    return True
                return False

            def _do_category_selection():
                if not _open_cat_modal():
                    logger.warning("Could not open category modal")
                    return False
                time.sleep(6)
                main_selected = _click_dropdown_option(cat_keyword, position="first")
                if not main_selected:
                    logger.warning("Main category selection failed for: %s", cat_keyword)
                else:
                    logger.info("Main category selected: %s", main_selected)
                    time.sleep(4)
                    # Use specific sub-category keyword to avoid "General"
                    sub_selected = _click_dropdown_option(subcat_keyword, position="last")
                    if sub_selected:
                        logger.info("Sub-category selected: %s", sub_selected)
                    else:
                        # Try without keyword — pick first non-General, non-empty option
                        sub_selected = page.evaluate("""() => {
                            const items = document.querySelectorAll(
                                'ul.a-list-link li a, li.a-dropdown-item a, .a-dropdown-link, ul[role=listbox] li a'
                            );
                            const visible = Array.from(items).filter(el => el.offsetParent !== null);
                            const t = visible.find(el => {
                                const txt = el.textContent.trim().toLowerCase();
                                return txt && txt !== 'select one' && txt !== 'general' && !txt.includes('kindle books');
                            });
                            if (t) { t.click(); return t.textContent.trim(); }
                            return null;
                        }""")
                        logger.info("Sub-category fallback selected: %s", sub_selected)
                        time.sleep(2)
                try:
                    checked = page.evaluate("""() => {
                        let n = 0;
                        for (const cb of document.querySelectorAll('input[type=checkbox]')) {
                            if (cb.offsetParent !== null && !cb.checked) { cb.click(); n++; }
                        }
                        return n;
                    }""")
                    if checked:
                        logger.info("Checked %d placement checkboxes", checked)
                        time.sleep(1)
                except Exception:
                    pass
                return _save_cat_modal()

            try:
                for cat_attempt in range(3):
                    success = _do_category_selection()
                    if success:
                        logger.info("Category selection done (attempt %d)", cat_attempt + 1)
                        break
                    logger.warning("Category attempt %d failed, retrying", cat_attempt + 1)
                    time.sleep(3)
            except Exception as e:
                logger.warning("Category selection failed: %s", e)

            time.sleep(2)

            # Screenshot before submitting to capture form state
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_before_submit.png"))
            # Log current field values for debugging
            try:
                field_values = page.evaluate("""() => {
                    const result = {};
                    const titleEl = document.querySelector('#data-title');
                    result.title = titleEl ? titleEl.value : null;
                    const inputs = document.querySelectorAll('input[type="text"], input[type="email"]');
                    const authorInputs = Array.from(inputs)
                        .filter(i => (i.name || i.id || '').toLowerCase().includes('contributor') || (i.name || i.id || '').toLowerCase().includes('author'))
                        .map(i => ({name: i.name, id: i.id, value: i.value}));
                    result.authorInputs = authorInputs;
                    const desc = document.querySelector('textarea, [contenteditable=true]');
                    result.descLen = desc ? (desc.value || desc.textContent || '').length : 0;
                    return result;
                }""")
                logger.info("Pre-submit field values: %s", field_values)
            except Exception:
                pass
            logger.info("Pre-submit screenshot saved")

            # Click Save & Continue — retry if still on details page (validation errors)
            def try_save_and_continue():
                for snc_sel in [
                    "button:has-text('Save and Continue')",
                    "button:has-text('Save & Continue')",
                    "button[type='submit']",
                ]:
                    try:
                        btn = page.locator(snc_sel).first
                        if btn.is_visible(timeout=5000):
                            btn.click()
                            page.wait_for_load_state("domcontentloaded", timeout=30000)
                            logger.info("Save & Continue via '%s', URL: %s", snc_sel, page.url)
                            time.sleep(3)
                            return True
                    except Exception:
                        continue
                return False

            try_save_and_continue()

            # ── After save: dismiss any popup FIRST (limit dialog, alerts, etc.) ──
            time.sleep(2)
            popup_after_save = _dismiss_any_popup()
            if popup_after_save:
                logger.info("Popup after save dismissed: %s", popup_after_save[:80])
                if "limit" in popup_after_save.lower():
                    page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_limit_popup.png"))
                    result.update(_kdp_error("account_limit"))
                    raise Exception("account_limit_reached")
                # Wait for page to settle after popup
                time.sleep(3)

            # Freeze URL immediately after navigation — avoids race condition where
            # page.url changes between the check and the log format call
            current_url = page.url
            import re as _re_url

            # If still on details page, try to recover
            if "details" in current_url:
                logger.warning("Still on details page after Save & Continue. URL: %s", current_url)

                # Check for popup one more time (can appear with delay)
                time.sleep(3)
                popup_retry = _dismiss_any_popup()
                if popup_retry:
                    logger.info("Delayed popup dismissed: %s", popup_retry[:80])
                    if "limit" in popup_retry.lower():
                        result["status"] = "error"
                        result["error"] = "account_limit_reached: Amazon title creation limit — wait for pending books to be approved."
                        raise Exception("account_limit_reached")
                    current_url = page.url
                    if "details" not in current_url:
                        logger.info("Page moved after popup dismiss: %s", current_url)

                # Log validation errors
                try:
                    error_texts = page.evaluate("""() => {
                        const errs = document.querySelectorAll('.a-alert-content, .a-form-error, [class*="error"], [class*="alert"]');
                        return Array.from(errs)
                            .map(e => e.textContent.trim())
                            .filter(t => t.length > 0 && t.length < 300)
                            .slice(0, 5);
                    }""")
                    if error_texts:
                        logger.warning("Validation errors: %s", error_texts)
                        # If category error, attempt one more category selection pass
                        if any('category' in e.lower() for e in error_texts):
                            logger.info("Category error detected — attempting emergency category selection")
                            try:
                                _do_category_selection()
                                time.sleep(2)
                                try_save_and_continue()
                                time.sleep(3)
                                _dismiss_any_popup()
                                current_url = page.url
                            except Exception as ce:
                                logger.warning("Emergency category selection failed: %s", ce)
                except Exception:
                    pass

                if "details" in current_url:
                    # Extract book ID from frozen URL
                    m = _re_url.search(r'title-setup/kindle/([^/]+)/details', current_url)
                    if m:
                        book_id = m.group(1)
                        if book_id == "new":
                            logger.warning("Book ID is 'new' — validation failed, book not created")
                            # Take a screenshot of what's on screen for debugging
                            page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_details_error.png"))
                            result.update(_kdp_error("details_rejected",
                                "Book ID is 'new' — KDP form validation failed. "
                                f"Screenshot saved: kdp_{genre}_details_error.png"))
                            result["screenshot"] = str(ROOT / "outputs" / "books" / f"kdp_{genre}_details_error.png")
                        else:
                            content_url = f"{KDP_URL}/en_US/title-setup/kindle/{book_id}/content"
                            logger.info("Navigating to content: %s", content_url)
                            page.goto(content_url, wait_until="domcontentloaded", timeout=30000)
                            time.sleep(3)
                            logger.info("Content page URL: %s", page.url)
            else:
                logger.info("Save & Continue succeeded — URL: %s", current_url)

            # ── STEP 6: Content Upload ───────────────────────────────────────
            # Skip remaining steps if book was never created (validation failed)
            if result.get("status") == "error":
                logger.warning("Skipping content/pricing steps — book not created")
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_final.png"))
                result["screenshot"] = str(ROOT / "outputs" / "books" / f"kdp_{genre}_final.png")
                raise Exception("Details validation failed — skipping to end")

            logger.info("Uploading manuscript... URL: %s", page.url)

            # Screenshot to see exact upload page state
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_upload_page.png"))

            # DRM: No DRM — scroll to top to make it visible, try multiple selectors
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
            drm_selected = False
            for drm_sel in [
                'input[value="false"][name*="drm"]',
                'input[value="0"][name*="drm"]',
                "label:has-text('Do not enable')",
                "label:has-text('No DRM')",
            ]:
                try:
                    el = page.locator(drm_sel).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        drm_selected = True
                        logger.info("DRM disabled via %s", drm_sel)
                        break
                except Exception:
                    continue
            if not drm_selected:
                # JS fallback
                try:
                    drm_result = page.evaluate("""() => {
                        const radios = document.querySelectorAll('input[type="radio"]');
                        for (const r of radios) {
                            if (r.name && r.name.toLowerCase().includes('drm') && (r.value === 'false' || r.value === '0')) {
                                r.click(); return r.id || r.value;
                            }
                        }
                        // Also try first DRM radio (which is typically "No")
                        const drmGroup = document.querySelectorAll('input[name*="drm"][type="radio"]');
                        if (drmGroup.length > 0) { drmGroup[0].click(); return 'first-drm'; }
                        return null;
                    }""")
                    if drm_result:
                        logger.info("DRM disabled via JS: %s", drm_result)
                except Exception:
                    pass

            def upload_file_via_chooser(file_path: str, upload_triggers: list) -> bool:
                """Click an upload button and intercept the file chooser dialog."""
                for trigger in upload_triggers:
                    try:
                        with page.expect_file_chooser(timeout=10000) as fc_info:
                            page.locator(trigger).first.click(timeout=5000)
                        fc_info.value.set_files(file_path)
                        logger.info("File chooser used with trigger: %s", trigger)
                        time.sleep(3)
                        return True
                    except Exception:
                        continue
                return False

            def js_expose_and_upload(file_path: str, input_selector: str) -> bool:
                """Fallback: expose hidden input via JS and set files directly."""
                try:
                    page.evaluate(f"""
                        var inputs = document.querySelectorAll('{input_selector}');
                        inputs.forEach(function(el) {{
                            el.style.display = 'block';
                            el.style.visibility = 'visible';
                            el.style.opacity = '1';
                            el.style.height = 'auto';
                            el.style.width = 'auto';
                            el.style.position = 'relative';
                            el.removeAttribute('hidden');
                        }});
                    """)
                    time.sleep(1)
                    upload_input = page.locator(input_selector).first
                    upload_input.set_input_files(file_path, timeout=15000)
                    return True
                except Exception as ex:
                    logger.debug("JS upload attempt failed for %s: %s", input_selector, ex)
                    return False

            # Try 1: File chooser approach (most reliable)
            manuscript_uploaded = upload_file_via_chooser(str(txt_path), [
                "text=Upload manuscript",
                "text=Upload Book Content",
                "text=Upload your manuscript",
                'button:has-text("Upload")',
                '[data-automation-id*="upload" i]',
                '.upload-area',
                '.upload-zone',
                '.drop-zone',
                'label[for*="file" i]',
                'label[for*="upload" i]',
                'label[for*="manuscript" i]',
            ])

            # Try 2: JS expose hidden input (fallback)
            if not manuscript_uploaded:
                for ms_sel in [
                    'input[type="file"]',
                    'input[type="file"][accept*=".txt"]',
                    'input[type="file"][accept*=".docx"]',
                    'input[type="file"][accept*=".epub"]',
                    '#data-upload-book-file',
                ]:
                    if js_expose_and_upload(str(txt_path), ms_sel):
                        manuscript_uploaded = True
                        logger.info("Manuscript uploaded (JS) via: %s", ms_sel)
                        break

            if manuscript_uploaded:
                # Wait for KDP to process the upload
                try:
                    page.wait_for_selector(
                        "text=Upload successful, text=processing, text=Manuscript uploaded, text=ready",
                        timeout=120000)
                    logger.info("Manuscript processing confirmed")
                except Exception:
                    time.sleep(15)  # Give it time anyway
            else:
                logger.warning("Could not upload manuscript automatically — saving progress")

            # Upload cover
            if cover_path and Path(cover_path).exists():
                logger.info("Uploading cover...")
                cover_uploaded = upload_file_via_chooser(cover_path, [
                    "text=Upload cover",
                    "text=Upload your cover",
                    'button:has-text("Upload cover")',
                    '[data-automation-id*="cover" i]',
                    'label[for*="cover" i]',
                ])
                if not cover_uploaded:
                    for cv_sel in [
                        'input[type="file"][accept*="image"]',
                        'input[type="file"][accept*=".jpg"]',
                        '#data-cover-image-input',
                    ]:
                        if js_expose_and_upload(cover_path, cv_sel):
                            cover_uploaded = True
                            logger.info("Cover uploaded (JS) via: %s", cv_sel)
                            time.sleep(5)
                            break
                if not cover_uploaded:
                    logger.warning("Cover upload failed — will use KDP cover creator")

            # Accessibility confirmation — KDP requires checking a box:
            # "I confirm that my answers are accurate"
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            try:
                acc_checked = page.evaluate("""() => {
                    const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                    let confirmed = 0;
                    for (const cb of checkboxes) {
                        if (!cb.checked) {
                            const lbl = document.querySelector('label[for="' + cb.id + '"]');
                            const txt = (lbl ? lbl.textContent : '').toLowerCase();
                            if (txt.includes('confirm') || txt.includes('accurate') || txt.includes('accessibility')) {
                                cb.click();
                                confirmed++;
                            }
                        }
                    }
                    return confirmed;
                }""")
                if acc_checked:
                    logger.info("Checked %d accessibility confirmation checkbox(es)", acc_checked)
                else:
                    # Try clicking all unchecked checkboxes on the page as fallback
                    acc_result = page.evaluate("""() => {
                        const boxes = document.querySelectorAll('input[type="checkbox"]:not(:checked)');
                        let n = 0;
                        for (const cb of boxes) {
                            if (cb.offsetParent !== null) { cb.click(); n++; }
                        }
                        return n;
                    }""")
                    if acc_result:
                        logger.info("Checked %d unchecked visible checkboxes", acc_result)
            except Exception as e:
                logger.warning("Accessibility checkbox failed: %s", e)

            time.sleep(1)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_content_before_save.png"))

            # Save & Continue (after upload)
            for snc2_sel in [
                "button:has-text('Save and Continue')",
                "button:has-text('Save & Continue')",
                "button[type='submit']",
            ]:
                try:
                    btn = page.locator(snc2_sel).first
                    if btn.is_visible(timeout=5000):
                        btn.click()
                        page.wait_for_load_state("domcontentloaded", timeout=30000)
                        logger.info("Save & Continue (2) via '%s', URL: %s", snc2_sel, page.url)
                        time.sleep(3)
                        break
                except Exception:
                    continue

            # If still on content page, extract book ID and navigate to pricing directly
            if "content" in page.url:
                import re as _re2
                m2 = _re2.search(r'title-setup/kindle/([^/]+)/content', page.url)
                if m2:
                    book_id2 = m2.group(1)
                    pricing_url = f"{KDP_URL}/en_US/title-setup/kindle/{book_id2}/pricing"
                    logger.info("Navigating directly to pricing: %s", pricing_url)
                    page.goto(pricing_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)
                    logger.info("Pricing page URL: %s", page.url)

            # ── STEP 7: Pricing ──────────────────────────────────────────────
            logger.info("Setting price: $%s — URL: %s", price, page.url)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_pricing.png"))

            # Territories: Worldwide
            for terr_sel in [
                'input[value="ALL"]',
                'input[value="worldwide" i]',
                "label:has-text('Worldwide')",
            ]:
                try:
                    t = page.locator(terr_sel).first
                    if t.is_visible(timeout=3000):
                        t.click()
                        break
                except Exception:
                    continue

            # Royalty plan: 70%
            for royalty_sel in [
                'input[value="0.70"]',
                'input[value="70"]',
                "label:has-text('70%')",
            ]:
                try:
                    r = page.locator(royalty_sel).first
                    if r.is_visible(timeout=3000):
                        r.click()
                        break
                except Exception:
                    continue

            # Set USD price
            price_filled = False
            for price_sel in [
                'input[name*="USD"]',
                'input[id*="USD"]',
                'input[placeholder*="price" i]',
                'input[name*="price" i]',
                'input[id*="price" i]',
            ]:
                try:
                    pi = page.locator(price_sel).first
                    if pi.is_visible(timeout=3000):
                        pi.click()
                        pi.fill(str(price))
                        pi.dispatch_event("input")
                        pi.dispatch_event("change")
                        price_filled = True
                        logger.info("Price $%s set via %s", price, price_sel)
                        time.sleep(1)
                        break
                except Exception:
                    continue

            if not price_filled:
                logger.warning("Could not set price on pricing page")

            time.sleep(2)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_pricing_filled.png"))

            # Save & Continue on pricing page before Publish
            for snc3_sel in [
                "button:has-text('Save and Continue')",
                "button:has-text('Save & Continue')",
            ]:
                try:
                    btn = page.locator(snc3_sel).first
                    if btn.is_visible(timeout=5000):
                        btn.click()
                        page.wait_for_load_state("domcontentloaded", timeout=30000)
                        logger.info("Save & Continue (3/pricing) via '%s', URL: %s", snc3_sel, page.url)
                        time.sleep(3)
                        break
                except Exception:
                    continue

            # ── STEP 8: Publish ──────────────────────────────────────────────
            logger.info("Publishing... URL: %s", page.url)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"kdp_{genre}_publish_page.png"))
            published = False
            for pub_sel in [
                "button:has-text('Publish Your Kindle eBook')",
                "button:has-text('Publish Your Kindle')",
                "button:has-text('Publish')",
                "input[type='submit'][value*='Publish' i]",
            ]:
                try:
                    btn = page.locator(pub_sel).first
                    if btn.is_visible(timeout=5000):
                        btn.click()
                        page.wait_for_load_state("domcontentloaded", timeout=30000)
                        time.sleep(5)
                        logger.info("Published! URL: %s", page.url)
                        result["status"] = "published"
                        result["kdp_url"] = page.url
                        published = True
                        break
                except Exception:
                    continue

            if not published:
                logger.warning("Publish button not found — saving screenshot")
                result["status"] = "review_required"
                result["note"] = "Reached pricing page — manual publish click may be needed"
                result["screenshot"] = str(ROOT / "outputs" / "books" / f"kdp_{genre}_final.png")
                page.screenshot(path=result["screenshot"])

        except PWTimeout as e:
            logger.error("Timeout during KDP upload: %s", e)
            screenshot = str(ROOT / "outputs" / "books" / f"kdp_{genre}_error.png")
            try:
                page.screenshot(path=screenshot)
            except Exception:
                pass
            result.update(_kdp_error("timeout", str(e)))
            result["screenshot"] = screenshot

        except Exception as e:
            err_msg = str(e)
            # Don't overwrite a pre-set error (e.g. account_limit, details validation)
            if not (result.get("status") == "error" and result.get("error")):
                logger.error("KDP upload error: %s", e)
                screenshot = str(ROOT / "outputs" / "books" / f"kdp_{genre}_error.png")
                try:
                    page.screenshot(path=screenshot)
                except Exception:
                    pass
                # Classify the error into a meaningful code
                err_lower = err_msg.lower()
                if "login" in err_lower or "password" in err_lower or "sign in" in err_lower:
                    result.update(_kdp_error("login_failed", err_msg[:200]))
                elif "mfa" in err_lower or "2fa" in err_lower or "otp" in err_lower or "verification" in err_lower:
                    result.update(_kdp_error("2fa_timeout", err_msg[:200]))
                elif "manuscript" in err_lower or "upload" in err_lower:
                    result.update(_kdp_error("manuscript_upload", err_msg[:200]))
                elif "cover" in err_lower or "image" in err_lower:
                    result.update(_kdp_error("cover_upload", err_msg[:200]))
                elif "price" in err_lower or "territory" in err_lower or "royalt" in err_lower:
                    result.update(_kdp_error("pricing_error", err_msg[:200]))
                elif "publish" in err_lower:
                    result.update(_kdp_error("publish_failed", err_msg[:200]))
                else:
                    result.update(_kdp_error("unknown", err_msg[:200]))
                result["screenshot"] = screenshot
            else:
                logger.info("Early exit: %s", err_msg)

        finally:
            context.close()
            browser.close()

    # Save result
    result_path = ROOT / "outputs" / "books" / f"kdp_result_{genre}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("KDP result: %s", result)

    # Telegram notification
    try:
        from core.telegram import notify
        emoji = "✅" if result["status"] == "published" else "⚠️"
        notify(f"{emoji} KDP Upload — {genre.title()}\nTitle: {title}\nStatus: {result['status']}\n💰 ${price}")
    except Exception:
        pass

    return result


def upload_all_genres(headless: bool = True) -> list:
    """Upload one book per genre to KDP. Stops if Amazon account limit is hit."""
    from bots.books.book_publisher import KDP_PRICES
    results = []
    account_limit_hit = False
    for genre in KDP_PRICES:
        if account_limit_hit:
            logger.warning("Skipping %s — account limit reached", genre)
            results.append({"genre": genre, "status": "skipped", "error": "account_limit_reached"})
            print(f"  ⏭ {genre}: skipped (account limit)")
            continue
        logger.info("Uploading genre: %s", genre)
        result = upload_book(genre, headless=headless)
        results.append(result)
        if result.get("error", "").startswith("account_limit_reached"):
            account_limit_hit = True
            logger.warning("Amazon title creation limit hit — stopping remaining genres")
        status = "✅" if result["status"] == "published" else "⏭" if result["status"] == "skipped" else "❌"
        print(f"  {status} {genre}: {result['status']}")
        time.sleep(5)  # Brief pause between uploads
    return results


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    p = argparse.ArgumentParser(description="Amazon KDP Automated Uploader")
    p.add_argument("--genre", type=str, help="Upload one genre")
    p.add_argument("--all", action="store_true", help="Upload all genres")
    p.add_argument("--cover-only", type=str, help="Generate cover for genre only")
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--visible", action="store_true", help="Show browser window")
    args = p.parse_args()

    headless = not args.visible

    if args.cover_only:
        path = generate_cover(args.cover_only, args.cover_only)
        print(f"✅ Cover: {path}")

    elif args.all:
        results = upload_all_genres(headless=headless)
        ok = sum(1 for r in results if r["status"] == "published")
        print(f"\n✅ {ok}/{len(results)} books published to KDP")

    elif args.genre:
        result = upload_book(args.genre, headless=headless)
        print(f"\n{'✅' if result['status'] == 'published' else '❌'} {args.genre}: {result}")

    else:
        print("Usage: python kdp_uploader.py --genre mystery  OR  --all  OR  --visible")
