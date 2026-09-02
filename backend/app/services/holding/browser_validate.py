"""BROWSER_VALIDATE runtime (Part A, §1-10) — A1 COMPUTE-VALIDATION, not open browser automation.

Validates SYSTEMS against server-owned validation suites. A task references only a validation_suite_id +
company_id + environment + target_resource_id (§2) — never arbitrary JS/script/shell/navigation program/
credential/cookie. The backend owns every suite definition (approved origins, allowed paths/methods,
side-effect policy, viewports, assertions). Read-only side effects only (§4): GET/navigate/inspect DOM/
a11y tree/screenshot/deterministic evaluate — never purchase/publish/submit/delete/settings/deploy/pay.
Origins are resolved from the registry, not task text (§6), with SSRF defense (no javascript:/file:/
private/metadata hosts). The Playwright runtime is INJECTED; with none wired it fails closed
(RUNTIME_PENDING) — the contract/origin/suite policy is still enforced before any runner is called.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse

from app.services.holding.task_resolver import redact


class BrowserDenied(Exception):
    """Raised for a bad contract, unknown suite, disallowed origin/scheme, or a mutation attempt."""


# §4 side-effect policy — only these are ever permitted.
READONLY_METHODS = frozenset({"GET"})
_MUTATION_MARKERS = re.compile(r"(?i)(POST|PUT|PATCH|DELETE|submit|purchase|checkout|pay|publish|"
                               r"delete|logout|rotate|deploy)")


@dataclass(frozen=True)
class ValidationSuite:
    suite_id: str
    approved_origins: tuple          # exact scheme://host[:port] allowlist
    allowed_paths: tuple = ("/",)
    allowed_methods: tuple = ("GET",)
    auth_required: bool = False
    screenshots: bool = True
    timeout_s: int = 30
    viewports: tuple = ("desktop",)
    assertions: tuple = ()
    allow_internal: bool = False     # only True for explicitly-registered internal validation targets


# Server-owned registry (§3). Origins are placeholders bound at deploy; empty approved_origins means the
# suite cannot run until ops registers the real origin → fail closed.
_SUITES: dict[str, ValidationSuite] = {
    "public_homepage_smoke": ValidationSuite("public_homepage_smoke", (), ("/",), ("GET",),
                                             assertions=("status_200", "title_present")),
    "holding_dashboard_smoke": ValidationSuite("holding_dashboard_smoke", (), ("/admin/holding",), ("GET",),
                                               auth_required=True, assertions=("today_section_present",)),
    "admin_capabilities_smoke": ValidationSuite("admin_capabilities_smoke", (), ("/admin/kai-capabilities.html",),
                                                ("GET",), auth_required=True),
    "responsive_layout": ValidationSuite("responsive_layout", (), ("/",), ("GET",),
                                         viewports=("desktop", "mobile")),
    "login_surface_presence": ValidationSuite("login_surface_presence", (), ("/admin",), ("GET",),
                                              assertions=("login_form_present",)),
    "health_ui": ValidationSuite("health_ui", (), ("/health",), ("GET",)),
    "known_workflow_readonly": ValidationSuite("known_workflow_readonly", (), ("/",), ("GET",)),
}

_SUITE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")


def register_validation_suite(suite: ValidationSuite) -> None:
    _SUITES[suite.suite_id] = suite


def resolve_suite(suite_id, *, suites: dict | None = None) -> ValidationSuite:
    if not isinstance(suite_id, str) or not _SUITE_ID_RE.match(suite_id):
        raise BrowserDenied("invalid validation_suite_id")
    sd = (suites if suites is not None else _SUITES).get(suite_id)
    if sd is None:
        raise BrowserDenied(f"unknown validation suite '{suite_id}'")
    return sd


@dataclass
class BrowserValidateRequest:
    validation_suite_id: str
    company_id: str
    environment: str = "staging"
    target_resource_id: str = ""
    correlation_id: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# task payload keys that must NEVER reach a browser runner (§2)
_FORBIDDEN_TASK_KEYS = {"script", "javascript", "js", "shell", "navigate", "program", "cookie",
                        "cookies", "credential", "credentials", "password", "eval", "code", "url"}


def _validate_origin(url: str, suite: ValidationSuite) -> str:
    """§6 origin policy + SSRF defense. Returns the validated URL or raises. The URL is built from the
    suite's approved origin + allowed path — task text never chooses an arbitrary URL."""
    p = urlparse(url or "")
    if p.scheme not in ("http", "https"):
        raise BrowserDenied(f"scheme '{p.scheme}' not allowed (only http/https)")   # blocks javascript:/file:/data:
    origin = f"{p.scheme}://{p.netloc}"
    if origin not in suite.approved_origins:
        raise BrowserDenied("target origin not in the suite allowlist")
    if p.path and not any(p.path == ap or p.path.startswith(ap.rstrip("/") + "/") or ap == "/"
                          for ap in suite.allowed_paths):
        raise BrowserDenied("target path not allowed by the suite")
    # SSRF: reject private/loopback/link-local/metadata hosts unless the suite explicitly allows internal
    host = p.hostname or ""
    if not suite.allow_internal:
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"):
            raise BrowserDenied("internal/metadata host denied")
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise BrowserDenied("private/reserved IP denied")
        except ValueError:
            pass   # not a literal IP — a hostname; the approved-origin allowlist above is the gate
    return url


def build_request(args: dict) -> BrowserValidateRequest:
    args = args or {}
    if _FORBIDDEN_TASK_KEYS & set(args):
        raise BrowserDenied("arbitrary script/url/cookie/credential is not permitted in a validation task")
    return BrowserValidateRequest(
        validation_suite_id=args.get("validation_suite_id", ""), company_id=args.get("company_id", ""),
        environment=args.get("environment", "staging"), target_resource_id=args.get("target_resource_id", ""),
        correlation_id=args.get("correlation_id", ""))


def _resolve_target(req: BrowserValidateRequest, suite: ValidationSuite) -> str:
    """Build the target URL from the suite's approved origin + allowed path (target_resource_id selects
    among approved origins/paths). Task text never supplies a raw URL."""
    origin = req.target_resource_id if req.target_resource_id in suite.approved_origins \
        else (suite.approved_origins[0] if suite.approved_origins else "")
    if not origin:
        raise BrowserDenied("no approved origin registered for this suite (runtime pending)")
    return _validate_origin(origin.rstrip("/") + suite.allowed_paths[0], suite)


def make_browser_validate_provider(*, runner=None, suites: dict | None = None):
    """Return provider(args) for the composite executor. Enforces the typed contract + suite + origin/SSRF
    policy BEFORE calling the injected Playwright runner. With no runner → CAPABILITY_UNAVAILABLE
    (RUNTIME_PENDING). A mutation-marked assertion/method is refused (§4). Evidence redacted (§7)."""
    def provider(args: dict) -> dict:
        req = build_request(args)
        suite = resolve_suite(req.validation_suite_id, suites=suites)
        # §4 read-only: the suite must declare only GET + no mutation-marked assertions
        if set(suite.allowed_methods) - READONLY_METHODS:
            raise BrowserDenied("suite declares a non-read-only method")
        if any(_MUTATION_MARKERS.search(a) for a in suite.assertions):
            raise BrowserDenied("suite declares a mutating assertion")
        target = _resolve_target(req, suite)
        if runner is None:
            # policy passed, but no Playwright runtime is wired on this server → fail closed, honestly.
            raise BrowserDenied("no browser runtime wired (BROWSER_VALIDATE_RUNTIME_PENDING)")
        raw = runner(target, suite)   # runner is a deterministic, read-only Playwright validation
        evidence = {"suite_id": suite.suite_id, "target": target, "environment": req.environment,
                    "viewports": list(suite.viewports),
                    "assertions": raw.get("assertions", []), "passed": raw.get("passed", 0),
                    "failed": raw.get("failed", 0), "console_errors": raw.get("console_errors", []),
                    "network_failures": raw.get("network_failures", []),
                    "screenshot_refs": raw.get("screenshot_refs", []),
                    "correlation_id": req.correlation_id, "observed_at": "now"}
        return redact(evidence)   # never a secret-bearing HTML dump (§7)

    return provider


if __name__ == "__main__":
    from app.services.holding.test_browser_validate import run
    run()
