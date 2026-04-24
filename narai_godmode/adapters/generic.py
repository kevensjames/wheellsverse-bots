"""
Generic browser adapter for services NarAI can log into with a password.
Good for: Printify admin, Shopify admin, most CMS, Bandcamp, DistroKid, SoundCloud upload, Etsy,
Squarespace, Canva, Notion (if no SSO), etc.
"""
from ..browser import Browser
from ..vault import Vault


# Pre-baked selectors for common services. Add more as you go.
SERVICE_PROFILES = {
    "printify": {
        "login_url": "https://printify.com/app/login",
        "email_sel": "input[name='email'], input[type='email']",
        "password_sel": "input[name='password'], input[type='password']",
        "submit_sel": "button[type='submit']",
        "home_url": "https://printify.com/app/dashboard",
    },
    "shopify": {
        "login_url": "https://accounts.shopify.com/store-login",
        "email_sel": "input[type='email']",
        "password_sel": "input[type='password']",
        "submit_sel": "button[type='submit']",
        "home_url": "https://www.shopify.com/admin",
    },
    "etsy": {
        "login_url": "https://www.etsy.com/signin",
        "email_sel": "#join_neu_email_field",
        "password_sel": "#join_neu_password_field",
        "submit_sel": "button[type='submit']",
        "home_url": "https://www.etsy.com/your/shops/me/dashboard",
    },
    "canva": {
        "login_url": "https://www.canva.com/login",
        "email_sel": "input[type='email']",
        "password_sel": "input[type='password']",
        "submit_sel": "button[type='submit']",
        "home_url": "https://www.canva.com/",
    },
}


def open_service(service: str, goto: str | None = None, headless: bool = False, keep_open: bool = True) -> None:
    service = service.lower()
    profile = SERVICE_PROFILES.get(service)
    if not profile:
        raise RuntimeError(
            f"No profile for '{service}'. Add one to SERVICE_PROFILES in generic.py, "
            f"or use the amazon_kdp adapter as a template."
        )

    creds = Vault().get(service)
    if not creds or creds["kind"] != "password":
        raise RuntimeError(
            f"No password creds for {service}. Run:\n"
            f"  python -m narai_godmode.cli set {service}"
        )

    target = goto or profile["home_url"]

    with Browser(service, headless=headless) as b:
        page = b.page()
        page.goto(target, wait_until="domcontentloaded")

        # Detect if login is needed
        if page.locator(profile["email_sel"]).first.is_visible(timeout=3000):
            page.fill(profile["email_sel"], creds["username"])
            page.fill(profile["password_sel"], creds["password"])
            page.click(profile["submit_sel"])
            page.wait_for_load_state("networkidle", timeout=30000)

            # 2FA pause
            otp_locator = page.locator("input[name*='otp' i], input[name*='code' i], input[autocomplete='one-time-code']")
            if otp_locator.first.is_visible(timeout=5000):
                input(f"[{service}] 2FA prompt - enter code in browser, press Enter here: ")

            page.goto(target, wait_until="domcontentloaded")

        print(f"[{service}] Ready -> {page.url}")

        if keep_open:
            input("Browser open. Press Enter here to close when done: ")
