"""Tests for BROWSER_VALIDATE (Part A, §1-10). Policy/attack tests are deterministic; the browser
runtime is injected. Run: python3 backend/app/services/holding/test_browser_validate.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.browser_validate import (  # noqa: E402
    make_browser_validate_provider, register_validation_suite, resolve_suite, ValidationSuite,
    BrowserDenied, _validate_origin)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


# a suite with a registered approved origin (as ops would configure for staging)
_SUITES = {"staging_home": ValidationSuite("staging_home", ("https://staging.example.com",), ("/",),
                                           ("GET",), assertions=("status_200",))}


def _ok_runner(target, suite):
    return {"assertions": ["status_200"], "passed": 1, "failed": 0, "console_errors": [],
            "network_failures": [], "screenshot_refs": ["shot-1.png"]}


def _args(**kw):
    base = {"validation_suite_id": "staging_home", "company_id": "kai", "environment": "staging",
            "target_resource_id": "https://staging.example.com"}
    base.update(kw)
    return base


def t_policy_cert_e2e_with_runner():
    """§8/§7: with an injected read-only runner + registered origin → real evidence."""
    prov = make_browser_validate_provider(runner=_ok_runner, suites=_SUITES)
    ev = prov(_args())
    assert ev["suite_id"] == "staging_home" and ev["passed"] == 1 and ev["target"].startswith("https://staging.example.com")
    assert "screenshot_refs" in ev


def t_no_runtime_fails_closed():
    """§10/§16: no browser runtime wired → denied (RUNTIME_PENDING), even for a valid request."""
    prov = make_browser_validate_provider(runner=None, suites=_SUITES)
    try:
        prov(_args()); assert False
    except BrowserDenied:
        pass


def t_arbitrary_script_url_cookie_denied():
    """§2: task can never supply script/url/cookie/credential."""
    prov = make_browser_validate_provider(runner=_ok_runner, suites=_SUITES)
    for bad in ({"script": "alert(1)"}, {"url": "https://evil.com"}, {"cookie": "session=x"},
                {"credential": "pw"}, {"javascript": "x"}, {"navigate": "prog"}):
        try:
            prov(_args(**bad)); assert False, bad
        except BrowserDenied:
            pass


def t_origin_and_scheme_ssrf_defense():
    """§6: only http/https + approved origins; javascript:/file:/private/metadata denied."""
    s = _SUITES["staging_home"]
    for bad in ("javascript:alert(1)", "file:///etc/passwd", "http://169.254.169.254/latest",
                "http://127.0.0.1/", "http://10.0.0.5/", "https://evil.com/"):
        try:
            _validate_origin(bad, s); assert False, bad
        except BrowserDenied:
            pass
    assert _validate_origin("https://staging.example.com/", s) == "https://staging.example.com/"


def t_unknown_and_bad_suite_id():
    prov = make_browser_validate_provider(runner=_ok_runner, suites=_SUITES)
    for bad in ("../../x", "rm -rf", "UNKNOWN", "a b"):
        try:
            prov(_args(validation_suite_id=bad)); assert False, bad
        except BrowserDenied:
            pass


def t_unregistered_origin_blocks():
    """A suite with no approved origin registered → cannot run (fail closed)."""
    prov = make_browser_validate_provider(runner=_ok_runner)   # default suites have empty origins
    try:
        prov({"validation_suite_id": "public_homepage_smoke", "company_id": "kai"}); assert False
    except BrowserDenied:
        pass


def t_mutation_suite_refused():
    """§4: a suite declaring a non-GET method or a mutating assertion is refused."""
    prov = make_browser_validate_provider(runner=_ok_runner, suites={
        "bad_method": ValidationSuite("bad_method", ("https://staging.example.com",), ("/",), ("POST",))})
    try:
        prov({"validation_suite_id": "bad_method", "company_id": "kai",
              "target_resource_id": "https://staging.example.com"}); assert False
    except BrowserDenied:
        pass
    prov2 = make_browser_validate_provider(runner=_ok_runner, suites={
        "bad_assert": ValidationSuite("bad_assert", ("https://staging.example.com",), ("/",), ("GET",),
                                      assertions=("submit_checkout_form",))})
    try:
        prov2({"validation_suite_id": "bad_assert", "company_id": "kai",
               "target_resource_id": "https://staging.example.com"}); assert False
    except BrowserDenied:
        pass


def t_no_secret_in_evidence():
    def leaky_runner(target, suite):
        return {"assertions": ["ok"], "passed": 1, "failed": 0,
                "console_errors": ["Authorization: Bearer super.secret.token"], "network_failures": [],
                "screenshot_refs": []}
    ev = make_browser_validate_provider(runner=leaky_runner, suites=_SUITES)(_args())
    assert "super.secret.token" not in str(ev)


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
