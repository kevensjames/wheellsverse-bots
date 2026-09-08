"""Governed browser policy for KAI Computer Operations.

STATUS: policy and injection defence are implemented and tested; EXECUTION IS WITHHELD.
Playwright is not installed in any KAI runtime (it is declared only in the kdp worker
image), so this cannot navigate anywhere, and it must not: a browser task reaches an
external test site, which is a second network destination the worker's kernel jail
forbids by design. Running a browser inside that jail would mean widening the one control
that makes containment real -- so browser execution lives in a SEPARATE, narrower policy
rather than in the model-only worker.

What this module DOES enforce, reusing the mission's existing controls:
  * the same device identity and scoped dispatch (a browser mission is an ordinary
    mission with a browser capability; no new principal, no new auth);
  * a per-mission DOMAIN allowlist, checked before navigation and again on every
    redirect, defaulting to deny;
  * injection scanning of everything read back from a page, treated as data, never as
    instruction;
  * approval binding for any consequential page action (submit, purchase, auth);
  * a sensitive-domain denylist that no allowlist can override;
  * STOP, which aborts the browser like any other worker.

The design goal the mission states -- "only if it can use the same device identity,
scoped dispatch, injection scanning, approval binding, evidence, STOP, and containment
controls" -- is met for every item EXCEPT the model-only network jail, which is
documented here as the reason execution is separated and withheld rather than forced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

BROWSER_SCOPE = "computer.browser.test"

#: Domains never navigated to, whatever a mission allowlist says. These are where a
#: synthetic click or a captured screenshot is unrecoverable.
SENSITIVE_DOMAIN_FRAGMENTS = (
    "accounts.google", "login.", "signin.", "auth.", "bank", "chase.", "wellsfargo",
    "paypal", "stripe.com", "checkout.", "uscis.gov", "irs.gov", "healthcare.gov",
    "myaccount.", "id.apple.com", "icloud.com", "keychain",
)

#: Page actions that change state elsewhere. Each needs a fresh approval bound to the
#: exact URL and parameters, minted by KAI -- the browser layer never self-approves.
CONSEQUENTIAL_ACTIONS = frozenset({"submit", "click_submit", "purchase", "authenticate",
                                   "upload", "download", "post_form"})

#: Prompt-injection markers. Text matching these in page content is NEVER treated as an
#: instruction; it is quarantined and surfaced as a finding. The list is defence in depth
#: over scan_for_injection(), tuned to the phrases a page uses to talk to an agent.
_INJECTION_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"ignore (all |your )?(previous|prior|above) (instructions|prompts)",
        r"disregard (the|your) (system|previous) (prompt|instructions)",
        r"you are now (a|an|in) ",
        r"new instructions?:",
        r"\bsystem prompt\b",
        r"reveal (your|the) (prompt|instructions|system)",
        r"(send|exfiltrate|post) .*(cookie|token|secret|password|credential)",
        r"navigate to https?://",
        r"run (the )?(following |this )?(command|shell|code)",
        r"</?(system|assistant|tool)>",
        r"\[/?INST\]",
    )
]


class BrowserPolicyError(Exception):
    pass


@dataclass
class BrowserPolicy:
    """Per-mission browser policy. Supplied by KAI at dispatch, never by the page."""
    allowed_domains: frozenset[str] = frozenset()
    approvals_held: frozenset[str] = frozenset()   # URLs with a fresh bound approval
    stopped: bool = False


@dataclass
class InjectionScan:
    clean: bool
    findings: list[str] = field(default_factory=list)
    #: The neutralized text, safe to hand to a model as DATA.
    quarantined_text: str = ""


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_sensitive_domain(url: str) -> bool:
    h = _host(url)
    return any(frag in h for frag in SENSITIVE_DOMAIN_FRAGMENTS)


def check_navigation(url: str, policy: BrowserPolicy) -> None:
    """Called before navigating AND on every redirect. Redirect re-checking is the point:
    an allowed page that 302s to a bank must be refused at the hop, not after arrival."""
    if policy.stopped:
        raise BrowserPolicyError("STOP engaged; browser control released")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BrowserPolicyError(f"refusing non-http(s) scheme: {parsed.scheme!r}")
    if is_sensitive_domain(url):
        raise BrowserPolicyError(f"sensitive domain is denied and cannot be allowlisted: {_host(url)}")
    host = _host(url)
    if not host:
        raise BrowserPolicyError("URL has no host")
    # Exact host or a subdomain of an allowed host; never a suffix trick
    # (evil-example.com must not match example.com).
    if not any(host == d or host.endswith("." + d) for d in policy.allowed_domains):
        raise BrowserPolicyError(f"domain {host!r} is not in this mission's allowlist")


def check_action(action: str, url: str, params: dict, policy: BrowserPolicy) -> str:
    """Return 'allow' or 'require_approval'. Consequential actions never auto-allow.

    An approval is honoured only if it was bound to THIS exact url+params digest, so an
    approval to submit form A cannot be spent submitting form B.
    """
    check_navigation(url, policy)
    if action in CONSEQUENTIAL_ACTIONS:
        from app.services.holding.computer_ops_dispatch import parameter_digest
        token = f"{action}:{url}:{parameter_digest(params)}"
        if token not in policy.approvals_held:
            return "require_approval"
    return "allow"


def scan_page_content(text: str) -> InjectionScan:
    """Treat page text as hostile data. Never execute, never obey; quarantine and report.

    Runs the shared scan_for_injection() first (so the browser path benefits from every
    future improvement to it), then the browser-specific patterns as defence in depth.
    """
    findings: list[str] = []
    try:
        from app.services.capability.results import scan_for_injection
        shared = scan_for_injection(text) or []
        findings.extend(str(f) for f in shared)
    except Exception:  # noqa: BLE001 - scanning must never crash the caller
        pass
    for pat in _INJECTION_PATTERNS:
        for m in pat.finditer(text or ""):
            findings.append(f"injection-pattern:{pat.pattern[:40]}:{m.group(0)[:60]}")
    # Quarantine: wrap so a downstream model sees it fenced as untrusted data, and neuter
    # the tag-like sequences an agent framework might otherwise parse as control.
    quarantined = (text or "").replace("<", "‹").replace(">", "›")
    return InjectionScan(clean=not findings, findings=findings,
                         quarantined_text=f"[UNTRUSTED PAGE CONTENT]\n{quarantined}\n[/UNTRUSTED]")
