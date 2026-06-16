"""
Strict result schema for all KDP pipeline operations.

Every KDP-touching function returns a KDPResult — no bare dicts, no `status`
strings without an evidence trail. The validators in `__post_init__` and
`can_transition` are intentionally strict because the May 19, 2026 "published
lie" was produced by code that constructed an unverified success status; see
`.claude/skills/truth_verification/SKILL.md` for the full incident. If a
caller hits `ValueError: ok=True requires evidence`, that is the immune
system doing its job — produce evidence or return a non-positive state.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Set


VALID_STATES: Set[str] = {
    # ━━━ Positive terminal states ━━━
    # Only these may co-occur with ok=True. Each requires evidence.
    "in_review",                  # confirmed submitted to KDP, awaiting Amazon review
    "live",                       # confirmed public on amazon.com/dp/[ASIN]
    "draft_saved",                # paperback auto_publish=False, draft persisted to bookshelf

    # ━━━ Publish-flow failure states ━━━
    "publish_unconfirmed",        # publish click fired, no confirmation observed
    "publish_button_missing",     # reached pricing, no publish button found
    "pricing_save_failed",        # pricing form filled, save did not advance
    "content_save_failed",        # content form filled, save did not advance
    "cover_upload_failed",        # cover step did not yield a visible cover
    "ai_disclosure_failed",       # AI disclosure radio did not register
    "details_save_failed",        # details form filled, save did not advance
    "categories_save_failed",     # categories modal did not save

    # ━━━ Pre-publish guard failures ━━━
    "stale_draft_blocking",       # existing= or item= param in create URL
    "wizard_stalled",             # expected step transition did not occur (includes Playwright timeouts)
    "account_limit_reached",      # Amazon's pending-titles cap hit, operator wait 24-72h
    "series_guard_blocking",      # Vol N upload blocked because Vol N-1 isn't live

    # ━━━ Manuscript / package failures ━━━
    "manuscript_file_missing",    # manuscript HTML/MD missing on disk
    "manuscript_incomplete",      # <8k words or missing ending marker, pre-validator
    "package_not_found",          # _read_kdp_package returned nothing
    "validation_failed",          # KDPValidator rejected the package

    # ━━━ Auth / credential failures ━━━
    "auth_failed",                # login flow returned not-authenticated
    "device_verification_required",  # CVF challenge, manual unblock needed
    "no_credentials",             # KDP_PASSWORD or KDP_EMAIL missing

    # ━━━ System states ━━━
    "queue_empty",                # no eligible book in queue or registry
    "unknown_error",              # outer exception, requires detail >=50 chars + screenshot
}

POSITIVE_TERMINAL_STATES: Set[str] = {"in_review", "live", "draft_saved"}


# Allowed state transitions for the same title. Validates registry updates.
# Format: { from_state: {allowed_to_states} }
# `None` represents "no prior state" (first-time entry).
ALLOWED_TRANSITIONS: Dict[Optional[str], Set[str]] = {
    None: VALID_STATES,                                      # new entry, any state allowed
    "queue_empty": VALID_STATES - {"live"},                  # never live from empty queue
    "publish_unconfirmed": {"in_review", "live", "publish_unconfirmed"},
    "in_review": {"in_review", "live", "publish_unconfirmed"},
    "live": {"live"},                                        # terminal — once live, always live

    # draft_saved can be promoted (paperback later finalizes) or stay; cannot
    # go back to a failure — once a draft exists on the bookshelf, the row is real.
    "draft_saved": {"draft_saved", "in_review", "live", "publish_unconfirmed"},

    # Cap-hit means no new publishing today. Cannot transition to live in the
    # same run cycle; can retry to in_review tomorrow after Amazon approves pending.
    "account_limit_reached": VALID_STATES - {"live"},

    # Series guard means we deliberately didn't try to publish. Cannot land
    # in a positive publish state from this guard — must clear the guard
    # and re-run.
    "series_guard_blocking": VALID_STATES - {"live", "in_review"},

    # Pure failure states can retry to anything.
    "publish_button_missing": VALID_STATES,
    "pricing_save_failed": VALID_STATES,
    "content_save_failed": VALID_STATES,
    "cover_upload_failed": VALID_STATES,
    "ai_disclosure_failed": VALID_STATES,
    "details_save_failed": VALID_STATES,
    "categories_save_failed": VALID_STATES,
    "stale_draft_blocking": VALID_STATES,
    "wizard_stalled": VALID_STATES,
    "auth_failed": VALID_STATES,
    "device_verification_required": VALID_STATES,
    "no_credentials": VALID_STATES,
    "manuscript_file_missing": VALID_STATES,
    "manuscript_incomplete": VALID_STATES,
    "package_not_found": VALID_STATES,
    "validation_failed": VALID_STATES,
    "unknown_error": VALID_STATES,
}


def can_transition(from_state: Optional[str], to_state: str) -> bool:
    """Return True if a state transition is allowed for the same title.

    Used by registry writers to reject downgrades (e.g. live → in_review)
    and impossible-from-this-point moves. `from_state=None` means
    first-time entry — any valid target state is allowed.
    """
    if to_state not in VALID_STATES:
        return False
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())


# Public Amazon ASIN format. Used by __post_init__ to gate state="live"
# and by registry writers (Part 4) to validate external_id before persisting.
_ASIN_PREFIXES = ("B0", "B1")
_ASIN_LEN = 10


def is_valid_public_asin(asin: Optional[str]) -> bool:
    """Strict check for public Amazon ASIN format.

    Public ASINs start with B0 or B1 followed by 8 alphanumerics
    (10 total). KDP's internal draft identifiers like `A23W5MA77RJT0B`
    are NOT public ASINs and must never be persisted as if they were.
    """
    if not asin or len(asin) != _ASIN_LEN:
        return False
    if not asin.startswith(_ASIN_PREFIXES):
        return False
    return asin.isalnum()


@dataclass
class Evidence:
    """Proof that a state transition actually occurred."""
    verified_by: str           # name of the is_*_confirmed helper
    observed_at: str           # ISO timestamp
    url: Optional[str] = None
    screenshot: Optional[str] = None
    dom_markers_seen: List[str] = field(default_factory=list)
    external_id: Optional[str] = None  # ASIN, draft id, etc.

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KDPResult:
    ok: bool
    state: str                 # must be in VALID_STATES
    genre: str
    title: Optional[str] = None
    evidence: Optional[Evidence] = None
    detail: str = ""
    screens_seen: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.state not in VALID_STATES:
            raise ValueError(
                f"Invalid KDPResult state '{self.state}'. "
                f"Must be one of: {sorted(VALID_STATES)}"
            )
        if self.ok and self.state not in POSITIVE_TERMINAL_STATES:
            raise ValueError(
                f"ok=True is only valid with state in {sorted(POSITIVE_TERMINAL_STATES)}, "
                f"got '{self.state}'"
            )
        if self.ok and self.evidence is None:
            raise ValueError(
                "ok=True requires evidence. No success without proof."
            )
        if self.ok and self.evidence and not self.evidence.verified_by:
            raise ValueError(
                "evidence.verified_by must name the helper that verified this result."
            )

        # state='live' is the strongest positive claim — require a real public ASIN.
        if self.state == "live":
            ext_id = self.evidence.external_id if self.evidence else None
            if not is_valid_public_asin(ext_id):
                raise ValueError(
                    f"state='live' requires evidence.external_id to be a real "
                    f"public ASIN (B0/B1 + 10 chars, alphanumeric); got {ext_id!r}. "
                    f"Internal KDP draft IDs like A23W5MA77RJT0B are not public ASINs."
                )

        # state='draft_saved' requires an identifier for the draft row.
        # Internal KDP IDs (e.g. A23W5MA77RJT0B) ARE valid here — that's exactly
        # what proves the draft was created. The asymmetry vs. 'live' is intentional.
        if self.state == "draft_saved":
            if self.evidence is None or not self.evidence.external_id:
                raise ValueError(
                    "state='draft_saved' requires evidence.external_id pointing to the "
                    "saved draft URL or KDP internal draft ID."
                )

        # state='unknown_error' is a friction-gated catch-all. Every use must
        # produce enough diagnostic data to retroactively classify into a specific
        # state next iteration. Over time, this state's usage should approach zero.
        if self.state == "unknown_error":
            if not self.detail or len(self.detail) < 50:
                raise ValueError(
                    "state='unknown_error' requires a detail string of at least 50 chars "
                    "describing what was caught, the exception type, and the traceback "
                    "summary. Use this state sparingly — prefer adding a specific state."
                )
            if self.evidence is None or self.evidence.screenshot is None:
                raise ValueError(
                    "state='unknown_error' requires evidence.screenshot. If Playwright "
                    "is unable to screenshot, save page.content() to a .html file "
                    "and reference that as the screenshot path instead."
                )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.evidence is None:
            d.pop("evidence", None)
        return d
