"""
Playwright session manager.
Each service gets its own persistent browser profile at ~/.narai/profiles/<service>/.
Log in ONCE per service - cookies persist, no password refills, no bot detection spikes.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext, Page


PROFILES_DIR = Path.home() / ".narai" / "profiles"


class Browser:
    """Use with `with Browser('amazon_kdp') as b: page = b.page()`."""

    def __init__(self, service: str, headless: bool = False):
        self.service = service
        self.headless = headless
        self.profile_dir = PROFILES_DIR / service
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "Browser":
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 800},
            # Reduce automation signals
            args=["--disable-blink-features=AutomationControlled"],
        )
        return self

    def __exit__(self, *args):
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()

    def page(self) -> Page:
        if not self.context:
            raise RuntimeError("Use inside `with Browser(...) as b:`")
        if self.context.pages:
            return self.context.pages[0]
        return self.context.new_page()

    def is_logged_in(self, check_url: str, check_selector: str) -> bool:
        """Navigate to check_url; return True if check_selector is visible."""
        page = self.page()
        page.goto(check_url, wait_until="domcontentloaded")
        try:
            return page.locator(check_selector).is_visible(timeout=5000)
        except Exception:
            return False
