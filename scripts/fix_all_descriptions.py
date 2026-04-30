#!/usr/bin/env python3
"""Fix KDP book descriptions for all 8 published ebooks — descriptions match actual story content."""
import os, time, logging, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(message)s")
log = logging.getLogger("fix_descriptions")

KDP_URL = "https://kdp.amazon.com"

# Descriptions written from actual manuscript content
BOOKS = [
    {
        "asin": "A34WMAQSO8ZOXH",
        "genre": "adventure",
        "title": "The Last Cartographer",
        "description": (
            "<p>When a bullet shatters the lamp six inches from her head, disgraced cartographer "
            "Dr. Elena Vasquez realizes the ancient map hidden in her grandfather's São Paulo workshop "
            "is worth dying for — or killing over.</p>"
            "<p>Fired from the Brazilian Geographic Institute for following impossible maps into the "
            "Amazon, Elena has nothing left to lose. But the ruthless, cultured man outside her window "
            "believes she holds the key to a discovery that could rewrite history — and he'll eliminate "
            "anyone standing in his way.</p>"
            "<p>Armed with four bullets, a centuries-old chart, and survival instincts forged in the "
            "favelas of Rio, Elena must outrun a well-resourced enemy across continents while deciphering "
            "a map that every serious cartographer has dismissed as legend.</p>"
            "<p><em>The Last Cartographer</em> is a pulse-pounding adventure thriller for readers who "
            "love globe-trotting action, ancient mysteries, and heroines who refuse to stay buried.</p>"
        ),
    },
    {
        "asin": "A2IAAK9I50XAEL",
        "genre": "historical",
        "title": "Letters from the Trenches",
        "description": (
            "<p>Geneva, 1917. Marguerite Dubois has been quietly forwarding letters between two young men "
            "destroyed by the same war — one fighting for France, one for Germany. Neither knows the other's "
            "true identity. Neither knows the woman translating their words has begun to love them both.</p>"
            "<p>What began as a small favor to a desperate professor has become the most dangerous secret "
            "in wartime Europe. Pierre Moreau writes from the trenches about Verlaine and pressed wildflowers "
            "found in shell craters. Heinrich writes from the other side about doubt, fear, and shrapnel in "
            "the soul. Marguerite sits between them, carrying their confessions across enemy lines — "
            "and carrying the weight of a deception that could destroy everyone involved.</p>"
            "<p>A haunting, intimate World War I novel about the impossible connections forged by war, "
            "the courage required to tell the truth, and what it means to know someone's heart without "
            "ever meeting their face.</p>"
        ),
    },
    {
        "asin": "A1YCMKIZFWDKB4",
        "genre": "romance",
        "title": "One More Sunrise",
        "description": (
            "<p>She's perched on a cliff above the Pacific at five-thirty in the morning, watching the "
            "sunrise after the five worst minutes of a three-year nightmare. He appears out of nowhere on "
            "the path behind her — rumpled, sleepless, carrying his own brand of exhaustion. Neither of "
            "them plans to talk. Neither of them can stop.</p>"
            "<p>Ellie came to this cliff when her life imploded. Daniel came because his carefully "
            "constructed world just fell apart too. Two strangers who should never have crossed paths, "
            "sharing the honesty that only seems possible in the dark, just before sunrise.</p>"
            "<p>But daylight has a way of complicating things — and the reasons they both ended up on "
            "that cliff are tangled in ways neither of them expected.</p>"
            "<p><em>One More Sunrise</em> is a warm, slow-burn second-chance romance about two broken "
            "people finding each other at exactly the wrong time — which turns out to be exactly right.</p>"
        ),
    },
    {
        "asin": "AXC151YT2YGR7",
        "genre": "sci_fi",
        "title": "Parallel You",
        "description": (
            "<p>Dr. Sarah Chen was trying to prove parallel universe communication was impossible. "
            "She accidentally proved the opposite.</p>"
            "<p>After three months of work, the quantum field calculations on her whiteboard point to "
            "a terrifying conclusion: consciousness itself creates entanglement across parallel timelines, "
            "and the equipment her university spent three million dollars on wasn't built to study particles "
            "— it was built to talk to them. To talk to us. To the versions of us who chose differently.</p>"
            "<p>When the machine beeps at midnight in an empty lab, Sarah and her department head freeze. "
            "Something is answering back — from the other side of a decision she made years ago, in a "
            "parallel life that went a different way.</p>"
            "<p>What would you say to another version of yourself? What would you sacrifice to change "
            "the path you're on?</p>"
            "<p><em>Parallel You</em> is a mind-bending science fiction thriller that asks whether the "
            "road not taken can ever find its way back to you.</p>"
        ),
    },
    {
        "asin": "A1EA7YK8USUA03",
        "genre": "self_help",
        "title": "Broke to Bitcoin",
        "description": (
            "<p>A 34-year-old construction supervisor gets a financial education from a McDonald's cashier. "
            "Marcus — twenty years old, phone paid off by crypto, car payment covered by crypto — reveals "
            "the embarrassingly simple strategy that changed everything: buy the same amount every payday, "
            "ignore the noise, and wait.</p>"
            "<p>That conversation sent the author down a research rabbit hole that turned everything he "
            "believed about \"safe\" money on its head. The savings account earning 0.01% interest wasn't "
            "protecting his money — inflation was quietly destroying it. The people who made the most "
            "money in crypto weren't traders or tech geniuses. They were boring, consistent, and patient.</p>"
            "<p>This is the book for working people who are tired of watching their savings lose value "
            "while everyone else seems to be building wealth. No jargon. No hype. No promises of getting "
            "rich overnight. Just the honest math behind Dollar Cost Averaging, which coins actually "
            "matter, and how to start with as little as fifty dollars.</p>"
            "<p><em>Broke to Bitcoin</em> is the no-nonsense crypto guide that treats you like an adult.</p>"
        ),
    },
    {
        "asin": "ARMVY39EPNIOM",
        "genre": "true_crime",
        "title": "Dark Web Diaries",
        "description": (
            "<p>At 3:17 AM, Detective Sarah Chen's encrypted app lights up with a notification that "
            "makes her stomach drop: Phoenix_Rising has uploaded 47 new files to Marketplace X — the "
            "dark web's most sophisticated criminal empire, and the case that has consumed the last "
            "eighteen months of her life.</p>"
            "<p>The Bureau's most prolific and elusive predator had gone silent for three weeks. Now "
            "they're back, and the volume and timing feel wrong. Orchestrated. Like Phoenix_Rising "
            "wants to be found.</p>"
            "<p>Sarah has spent months building an undercover identity inside Marketplace X, a layered "
            "criminal economy protected by Tor, cryptocurrency, and the kind of operational security "
            "that makes traditional police work feel obsolete. But the metadata buried in Phoenix_Rising's "
            "new uploads contains a digital fingerprint — and a pattern suggesting their target is "
            "getting sloppy. Or desperate.</p>"
            "<p>In a world where criminals hide behind encryption and law enforcement chases shadows "
            "through fiber optic cables, <em>Dark Web Diaries</em> is a gripping true crime investigation "
            "into the digital underground — and what it costs to bring it down.</p>"
        ),
    },
    {
        "asin": "ADJA7L9B8IQHP",
        "genre": "mystery",
        "title": "Seven Suspects, One Alibi",
        "description": (
            "<p>Seven strangers. One dead body. One impossible alibi.</p>"
            "<p>When Blackwood is found murdered in his office, Detective Maya expects the usual "
            "suspects. Instead, she finds seven people — a nervous accountant, an elderly widow, "
            "a purple-haired barista, a security guard, an art dealer, a college student, and a yoga "
            "instructor — all sharing the exact same alibi: they were trapped together in the building's "
            "elevator from 3:17 PM to 4:43 PM. Security footage confirms it. Emergency call logs confirm "
            "it. Digital timestamps confirm it.</p>"
            "<p>It's airtight. Unbreakable. Perfect.</p>"
            "<p>Too perfect. Because the building's visitor logs show three of them were never "
            "supposed to be there at all.</p>"
            "<p>As Maya peels back the careful coincidences that brought seven strangers into one elevator "
            "at exactly the right moment, she discovers that someone planned this very carefully — and "
            "the most dangerous person in the room has been watching her through the glass the entire time.</p>"
            "<p><em>Seven Suspects, One Alibi</em> is a locked-room mystery that will keep you guessing "
            "until the very last page.</p>"
        ),
    },
    {
        "asin": "ABQLGHD2VX3WV",
        "genre": "fantasy",
        "title": "The Debt Collector of Souls",
        "description": (
            "<p>Kira collects years. Not metaphorically — she presses her palm to a debtor's forehead "
            "and watches their hair turn white as stolen time flows into the crystal vial on her wrist. "
            "Three years for a medicine that saved a husband's life. Two decades for a second chance. "
            "Whatever you borrowed from the Chronarch Bank, she comes to collect.</p>"
            "<p>For seven years she has done this work without question. But after gathering nearly two "
            "centuries of human life — from the desperate, the dying, the hopeful — Kira realizes she "
            "has no idea where any of it goes. The bank's vaults hold enough stolen time to give every "
            "person in Temporis City an extra decade. Yet the waiting lists for time purchase keep growing.</p>"
            "<p>Then a silver-haired stranger steps out of shadows too shallow to hide him and asks the "
            "question she's been afraid to ask herself: <em>What do they do with it all?</em></p>"
            "<p>A dark fantasy of time magic, moral reckoning, and the cost of serving a system you "
            "finally stop believing in. <em>The Debt Collector of Souls</em> is the story of a woman "
            "who built her life collecting debts — until she discovers the greatest debt of all has "
            "always been her own.</p>"
        ),
    },
]


def fill_field(page, selectors, value, label="field"):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=5000):
                el.click(click_count=3)
                time.sleep(0.3)
                el.fill(value)
                el.dispatch_event("input")
                el.dispatch_event("change")
                log.info("  %s set (%d chars)", label, len(value))
                return True
        except Exception as ex:
            log.debug("  selector failed [%s]: %s", sel, ex)
    return False


def fix_description(page, asin: str, description: str) -> bool:
    url = f"{KDP_URL}/en_US/title-setup/kindle/{asin}/details"
    log.info("Navigating to %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    time.sleep(5)

    # KDP uses CKEditor for the description — set via JS API
    filled = False
    try:
        has_cke = page.evaluate("() => typeof window.CKEDITOR !== 'undefined'")
        if has_cke:
            # Escape the HTML for safe JS injection
            escaped = description.replace("\\", "\\\\").replace("`", "\\`")
            page.evaluate(f"() => window.CKEDITOR.instances['editor1'].setData(`{escaped}`)")
            # Also update the hidden input so the form submits the value
            page.evaluate(
                f"() => {{ const h = document.querySelector('input[name=\"data[description]\"]'); "
                f"if (h) h.value = `{escaped}`; }}"
            )
            log.info("  Description set via CKEditor (%d chars)", len(description))
            filled = True
    except Exception as ex:
        log.warning("  CKEditor approach failed: %s", ex)

    if not filled:
        log.warning("  Could not set description for ASIN %s", asin)
        page.screenshot(path=str(ROOT / "outputs" / "books" / f"desc_debug_{asin}.png"))
        return False

    time.sleep(1)

    # Save & Continue
    for sel in ["button:has-text('Save and Continue')", "button:has-text('Save & Continue')"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=5000):
                btn.click()
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                time.sleep(3)
                log.info("  Saved. URL: %s", page.url)
                return True
        except Exception:
            pass

    log.warning("  Save button not found for ASIN %s", asin)
    return False


def main():
    from playwright.sync_api import sync_playwright

    email = os.getenv("KDP_EMAIL", "")
    password = os.getenv("KDP_PASSWORD", "")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=150)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        page.set_default_timeout(60000)

        # Login
        log.info("Logging in to KDP...")
        page.goto(f"{KDP_URL}/en_US/", wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        try:
            page.locator("a:has-text('Sign in')").first.click()
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
        except Exception:
            pass
        try:
            page.locator("#ap_email").first.fill(email)
            page.locator("#continue").first.click()
            time.sleep(2)
        except Exception:
            pass
        page.locator("#ap_password").first.fill(password)
        page.locator("#signInSubmit").first.click()
        time.sleep(6)
        log.info("Logged in: %s", page.url)

        results = []
        for book in BOOKS:
            log.info("\n── %s (%s) ──", book["title"], book["asin"])
            ok = fix_description(page, book["asin"], book["description"])
            results.append((book["title"], "✅ Fixed" if ok else "⚠️ Failed"))

            # Also update registry
            try:
                reg_path = ROOT / "data" / "kdp_registry.json"
                data = json.loads(reg_path.read_text())
                for e in data:
                    if e.get("asin") == book["asin"] or book["asin"] in e.get("kdp_url", ""):
                        e["description"] = book["description"]
                reg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            except Exception as re:
                log.warning("  Registry update failed: %s", re)

        context.close()
        browser.close()

    print("\n─── Results ───")
    for title, status in results:
        print(f"{status}: {title}")
    print("\nDone. KDP may take a few minutes to display the new descriptions.")


if __name__ == "__main__":
    main()
