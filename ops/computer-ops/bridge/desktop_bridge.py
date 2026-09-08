"""KAI desktop bridge — the ONLY path to macOS desktop interaction.

Why this exists as a separate component
---------------------------------------
The pinned DeepSeek Harness has no desktop capability at all (repo-wide searches for
robotjs, nut-js, CGEvent, AXUIElement, screencapture, desktopCapturer return nothing).
That absence is a feature, and this bridge must not undo it. It is a SIBLING of the
harness, invoked only by the KAI connector. It is never mounted as a harness tool and
is never reachable from harness bash -- which is also why `tool-bash` is disabled in
00-containment.patch.yml: the macOS sandbox denies only `file-write*`, so a mounted
shell could invoke `screencapture` and `osascript` directly, with no bridge, no
permission check, and no KAI audit record.

Design constraints this file enforces
-------------------------------------
1. CLOSED VERB VOCABULARY. Callers name a verb from `VERBS` and pass typed arguments.
   There is no command string, anywhere. A verb maps to a fixed argv built here, so a
   caller cannot inject arguments the way a shell string would allow.
2. DETERMINISTIC, ORDERED CHECKS. Every request runs the same gate sequence, outside
   any model, before a process is spawned. The order matters: the cheapest and most
   absolute denials come first so a later check can never re-open an earlier one.
3. TRUTHFUL CAPABILITY REPORTING. Availability comes from PROBING the OS, never from a
   config flag. A bridge that says "ready" because someone set a boolean is exactly the
   fake-readiness the mission forbids.
4. NO CREDENTIAL SURFACES. Password managers, keychains and browser cookie stores are
   denied by path regardless of any allowlist.

This module performs no network I/O and holds no secrets.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# --- capability reporting ---------------------------------------------------


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    #: The host has no interactive desktop at all (headless server, SSH-only session).
    #: A Linux server cannot drive a Mac desktop without an enrolled Mac helper.
    DESKTOP_UNAVAILABLE = "DESKTOP_UNAVAILABLE"
    #: There is a desktop, but macOS has not granted this binary the TCC permission the
    #: verb needs. Only the operator can grant it, in System Settings.
    PERMISSION_NOT_GRANTED = "PERMISSION_NOT_GRANTED"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    #: Consequential: KAI must obtain a fresh operator approval bound to device, action,
    #: target, parameters, scope and expiry before this may proceed.
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


# --- verb vocabulary --------------------------------------------------------


@dataclass(frozen=True)
class Verb:
    name: str
    #: Human description shown in the approval dossier.
    description: str
    #: TCC service this verb needs, or None when it needs no special grant.
    tcc: str | None
    #: True when the verb changes observable state outside KAI (input synthesis,
    #: launching applications). Read-only observation is False.
    mutating: bool
    #: True when the verb captures screen content, which is opt-in and minimally retained.
    captures_screen: bool = False


VERBS: dict[str, Verb] = {
    "probe": Verb("probe", "Report desktop availability and permission state", None, False),
    "list_windows": Verb(
        "list_windows", "List titles of visible windows of approved applications",
        "Accessibility", False),
    "capture_screen": Verb(
        "capture_screen", "Capture the full screen to an artifact file",
        "ScreenCapture", False, captures_screen=True),
    "capture_window": Verb(
        "capture_window", "Capture one approved application window",
        "ScreenCapture", False, captures_screen=True),
    "launch_app": Verb(
        "launch_app", "Launch an approved application", None, True),
}

#: Verbs each autonomy mode may reach. OBSERVE deliberately cannot capture the screen:
#: a screenshot is a disclosure of whatever happens to be on the display, so it is
#: opt-in per mission rather than implied by read-only inspection.
MODE_VERBS: dict[str, frozenset[str]] = {
    "OBSERVE": frozenset({"probe", "list_windows"}),
    "ASSIST": frozenset({"probe", "list_windows", "capture_window"}),
    "EXECUTE_SCOPED": frozenset({"probe", "list_windows", "capture_window", "capture_screen", "launch_app"}),
}

#: Applications whose contents must never be captured. Masking a region cannot be
#: guaranteed across window moves, overlays and Spaces changes, so capture is BLOCKED
#: rather than masked when one of these is the target.
SENSITIVE_APPS = frozenset({
    "1Password", "1Password 7", "1Password 8", "Bitwarden", "KeePassXC", "Dashlane",
    "LastPass", "Keychain Access", "Passwords", "Authy", "Secretive", "Proton Pass",
})

#: Path fragments that must never be read by any verb, regardless of allowlists.
FORBIDDEN_PATH_PATTERNS = tuple(
    re.compile(p) for p in (
        r"/\.ssh(/|$)", r"/\.aws(/|$)", r"/\.gnupg(/|$)", r"/\.config/gcloud(/|$)",
        r"/Library/Keychains(/|$)", r"/\.netrc$", r"/\.env(\.|$)", r"\.pem$", r"\.key$",
        r"/Cookies(/|$)", r"/Login Data(/|$)",
    )
)


@dataclass
class BridgePolicy:
    """Deterministic policy for one mission. Supplied by KAI, never by the model."""

    mode: str
    #: Applications this mission may touch, by name. Empty means none -- the default is
    #: deny, so a mission that forgot to declare targets can do nothing.
    allowed_apps: frozenset[str] = frozenset()
    #: Master kill switch. STOP sets this and every verb refuses immediately.
    stopped: bool = False
    #: Screen capture must be enabled per mission by the operator, never by default.
    screen_capture_opt_in: bool = False


@dataclass
class BridgeResult:
    decision: Decision
    availability: Availability | None = None
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.decision is Decision.ALLOW


# --- host probing (truthful, never a flag) ----------------------------------


def has_interactive_desktop() -> bool:
    """True only when this host actually has a logged-in GUI session.

    Probed, not configured. `launchctl managername` reports `Aqua` for a GUI session
    and `Background`/`StandardIO` otherwise, so an SSH-only or headless host is
    reported honestly instead of failing later at the first capture.
    """
    if os.uname().sysname != "Darwin":
        return False
    try:
        out = subprocess.run(["launchctl", "managername"], capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and out.stdout.strip() == "Aqua"


def probe_screen_recording() -> bool:
    """Probe the Screen Recording grant by attempting a real one-pixel capture.

    macOS exposes no supported API to ask 'am I granted?' without attempting the
    operation, and the TCC database is SIP-protected and not authoritative for this
    process's identity. Attempting the smallest possible capture to a temporary file is
    the only honest probe: it either produced a file or it did not.
    """
    if not has_interactive_desktop() or shutil.which("screencapture") is None:
        return False
    tmp = "/tmp/.kai_bridge_probe.png"
    try:
        subprocess.run(["screencapture", "-x", "-R", "0,0,1,1", tmp],
                       capture_output=True, timeout=10)
        return os.path.exists(tmp) and os.path.getsize(tmp) > 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def probe_accessibility() -> bool:
    """Probe the Accessibility grant by asking System Events for a trivial fact.

    Without the grant osascript returns a non-zero status with a -1743 error rather
    than an empty result, so a successful read is the evidence.
    """
    if not has_interactive_desktop() or shutil.which("osascript") is None:
        return False
    try:
        out = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to return count of processes'],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and out.stdout.strip().isdigit()


def capability_report() -> dict[str, Any]:
    """Everything a dashboard needs to render desktop status honestly."""
    desktop = has_interactive_desktop()
    return {
        "interactive_desktop": desktop,
        "screen_recording_granted": probe_screen_recording() if desktop else False,
        "accessibility_granted": probe_accessibility() if desktop else False,
        "platform": os.uname().sysname,
        # Named so an operator can find the exact toggles; these are the only way to
        # grant them and KAI cannot set them.
        "grant_location": "System Settings > Privacy & Security > "
                          "{Screen Recording, Accessibility}",
    }


# --- the gate ---------------------------------------------------------------


def _tcc_granted(service: str | None) -> bool:
    if service is None:
        return True
    if service == "ScreenCapture":
        return probe_screen_recording()
    if service == "Accessibility":
        return probe_accessibility()
    return False


def evaluate(verb_name: str, policy: BridgePolicy, *, target_app: str | None = None,
             target_path: str | None = None) -> BridgeResult:
    """Ordered, deterministic permission checks. No model participates.

    Order is deliberate and must not be reshuffled: STOP outranks everything, an
    unknown verb is refused before any allowlist can be consulted, and capability
    probing happens last so a denied request never spawns a process.
    """
    # 1. STOP outranks every other consideration, including an explicit allowlist.
    if policy.stopped:
        return BridgeResult(Decision.DENY, reason="STOP is engaged; desktop control is released")

    # 2. Closed vocabulary. An unrecognised verb is refused, never passed through.
    verb = VERBS.get(verb_name)
    if verb is None:
        return BridgeResult(Decision.DENY, reason=f"unknown verb {verb_name!r}")

    # 3. Mode allowlist. An unknown mode grants nothing (deny by default).
    if verb_name not in MODE_VERBS.get(policy.mode, frozenset()):
        return BridgeResult(
            Decision.DENY,
            reason=f"verb {verb_name!r} is not permitted in autonomy mode {policy.mode!r}")

    # 4. Forbidden paths, regardless of any allowlist. Checked before target rules so a
    #    permissive app allowlist can never reach a credential store.
    if target_path is not None:
        for pat in FORBIDDEN_PATH_PATTERNS:
            if pat.search(target_path):
                return BridgeResult(Decision.DENY,
                                    reason=f"path matches a forbidden credential pattern: {pat.pattern}")

    # 5. Sensitive applications are never captured. Masking cannot be guaranteed across
    #    window moves and Spaces changes, so capture is blocked rather than masked.
    if target_app is not None and verb.captures_screen and target_app in SENSITIVE_APPS:
        return BridgeResult(Decision.DENY,
                            reason=f"capture of sensitive application {target_app!r} is blocked, not masked")

    # 6. Target allowlist. Default-empty: a mission that declares no apps reaches none.
    if target_app is not None and target_app not in policy.allowed_apps:
        return BridgeResult(Decision.DENY,
                            reason=f"application {target_app!r} is not in this mission's approved targets")

    # 7. Screen capture is opt-in per mission, never implied by the mode.
    if verb.captures_screen and not policy.screen_capture_opt_in:
        return BridgeResult(Decision.DENY,
                            reason="screen capture is not opted in for this mission")

    # 8. Capability probe LAST, so a policy-denied request never touches the OS and
    #    never triggers a permission dialog the operator did not ask for.
    if not has_interactive_desktop():
        return BridgeResult(Decision.DENY, availability=Availability.DESKTOP_UNAVAILABLE,
                            reason="host has no interactive desktop session")
    if not _tcc_granted(verb.tcc):
        return BridgeResult(
            Decision.DENY,
            availability=Availability.PERMISSION_NOT_GRANTED,
            reason=f"macOS has not granted {verb.tcc} to this bridge; "
                   f"the operator must grant it in System Settings")

    # 9. Mutating verbs are consequential and require a fresh, bound operator approval.
    #    The bridge never grants that itself -- it reports the requirement upward so the
    #    approval is minted and burned by KAI, bound to device/action/target/expiry.
    if verb.mutating:
        return BridgeResult(Decision.REQUIRE_APPROVAL, availability=Availability.AVAILABLE,
                            reason=f"{verb_name} changes state outside KAI and needs a fresh bound approval")

    return BridgeResult(Decision.ALLOW, availability=Availability.AVAILABLE, reason="permitted")
