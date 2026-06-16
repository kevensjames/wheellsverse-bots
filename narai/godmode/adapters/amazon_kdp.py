"""
Amazon KDP adapter.
Opens KDP, signs in if the cookie is dead, navigates to the goal page.
Leaves the browser open for NarAI / you to continue the task.
"""
from ..browser import Browser
from ..vault import Vault


GOALS = {
    "bookshelf": "https://kdp.amazon.com/en_US/bookshelf",
    "create_book": "https://kdp.amazon.com/en_US/title-setup/kindle/new",
    "create_paperback": "https://kdp.amazon.com/en_US/title-setup/paperback/new/details",
    "reports": "https://kdp.amazon.com/en_US/reports-new",
    "payments": "https://kdp.amazon.com/en_US/reports-new/payments",
}


def open_kdp(goal: str = "bookshelf", headless: bool = False, keep_open: bool = True) -> None:
    creds = Vault().get("amazon_kdp")
    if not creds or creds["kind"] != "password":
        raise RuntimeError(
            "No password creds for amazon_kdp. Run:\n"
            "  python -m narai.godmode.cli set amazon_kdp"
        )

    target = GOALS.get(goal, GOALS["bookshelf"])

    with Browser("amazon_kdp", headless=headless) as b:
        page = b.page()
        page.goto(target, wait_until="domcontentloaded")

        # Sign-in form showing? Fill it.
        if page.locator("#ap_email, input[name='email']").first.is_visible(timeout=3000):
            _do_signin(page, creds["username"], creds["password"])

        # Re-navigate to the goal (post-login redirect may send you elsewhere)
        page.goto(target, wait_until="domcontentloaded")

        print(f"[KDP] Ready on {goal} -> {page.url}")

        if keep_open:
            input("Browser open. Press Enter here to close when done: ")


def _do_signin(page, email: str, password: str) -> None:
    # Email step
    page.fill("#ap_email, input[name='email']", email)
    page.click("#continue, input#continue, input[type='submit']")

    # Password step
    page.wait_for_selector("#ap_password, input[name='password']", timeout=15000)
    page.fill("#ap_password, input[name='password']", password)

    # Remember-me box (keeps you logged in longer)
    try:
        page.check("input[name='rememberMe']")
    except Exception:
        pass

    page.click("#signInSubmit, input#signInSubmit")

    # 2FA / OTP? Pause for user.
    try:
        page.wait_for_selector("input[name='otpCode'], #auth-mfa-otpcode", timeout=7000)
        input("[KDP] 2FA prompt - enter the code in the browser, then press Enter here: ")
        page.click("input[type='submit']")
    except Exception:
        pass  # no 2FA this time
