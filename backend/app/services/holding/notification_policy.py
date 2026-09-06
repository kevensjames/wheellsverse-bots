"""§31 single NotificationPolicy — the ONE funnel every holding emitter consults before the owner is
alerted. Consolidation, not a new sender: it decides *whether* to notify (the 7 allowed reasons only,
suppressing routine/duplicate/unchanged/low-confidence) and delegates the actual send to the EXISTING
delivery.send_alert (opt-in, default OFF — unchanged here). No per-feature sender, no parallel queue.

Reuse map (do not fork these):
  - delivery.send_alert          the ONE transport (Telegram, opt-in default OFF). We never bypass it.
  - self_improvement_detect      the Db/InMemory single-JSONB-row store shape + the "record on decision,
                                 not on transport success" dedup semantic (mirrored below).
  - watch.diff                   the spam-free "unchanged → no alert" property (content-hash based here).

Zero-fabrication (§0 #16-19): an event with no evidence_ref is NOT evidence-backed → suppressed. The
policy cannot audit evidence *content* (upstream detectors do), only that a citation is present.

Bounded/no-LLM-loop (§79): pure/deterministic decision; injectable clock + state; never raises fatally.

BAKED-IN fix (prior-pass review): timestamps are parsed FULL-FIDELITY —
    datetime.fromisoformat(str(t).replace('Z','+00:00'))  # no slicing, no [:26]
then normalized to UTC (naive assumed UTC) before subtracting, so a microsecond+offset timestamp
computes the correct age. (The [:26]/replace('Z','') pattern in holding_problems.py /
self_improvement_signals.py DROPS the tz and truncates — do not copy it.)
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from uuid import uuid4

# ── the 7 (and only 7) reasons the owner may be notified (§31) ─────────────────────────────────────────
CRITICAL_MATERIAL_CHANGE   = "critical_material_change"
HIGH_VALUE_OPPORTUNITY     = "high_value_opportunity"
REQUIRED_DECISION          = "required_decision"
MISSION_COMPLETION         = "mission_completion"
REPEATED_FAILURE           = "repeated_failure"
SECURITY_FINDING           = "security_finding"
SCHEDULED_EXECUTIVE_BRIEF  = "scheduled_executive_brief"
ALLOWED_REASONS = frozenset({
    CRITICAL_MATERIAL_CHANGE, HIGH_VALUE_OPPORTUNITY, REQUIRED_DECISION, MISSION_COMPLETION,
    REPEATED_FAILURE, SECURITY_FINDING, SCHEDULED_EXECUTIVE_BRIEF})

DEFAULT_COOLDOWN_SECONDS = 6 * 3600     # re-fire of the same dedupe_key inside this window is suppressed
DEFAULT_MIN_CONFIDENCE   = 0.5          # below this → low-confidence, suppressed
_PRUNE_SECONDS           = 30 * 24 * 3600
# evidence-quality tiers (§58) mapped to a scalar so callers may pass either a tier or a float.
_CONF_TIER = {"HIGH": 0.9, "MEDIUM": 0.6, "MED": 0.6, "LOW": 0.2, "UNKNOWN": 0.0, "": 0.0}


@dataclass
class NotificationEvent:
    """The single event model every emitter builds (§96 one model, no per-feature provider)."""
    category: str                                 # one of ALLOWED_REASONS; anything else = routine → suppress
    title: str
    summary: str = ""
    severity: str = "INFO"                         # CRITICAL | HIGH | MEDIUM | INFO
    company: str = ""                              # entity_id, or "" for holding-wide
    mission: str = ""                              # mission_id, or "" if not mission-bound
    evidence_ref: str = ""                         # a citation (proposal/mission/suite/probe id/url) — REQUIRED
    owner_action_required: bool = False
    confidence: object = "HIGH"                    # tier str (HIGH/MEDIUM/LOW) or float 0..1
    created_at: str = ""                           # emitter's iso ts; "" → stamped at notify()
    dedupe_key: str = ""                           # stable per root; "" → derived from category+company+title
    event_id: str = field(default_factory=lambda: uuid4().hex[:12])
    delivery_state: str = "PENDING"                # PENDING | SENT | DELIVERY_OFF | NOT_DELIVERED | SUPPRESSED

    def key(self) -> str:
        return self.dedupe_key or f"{self.category}:{self.company}:{self.title}".strip(":")

    def content_hash(self) -> str:
        raw = f"{self.severity}|{self.title}|{self.summary}|{int(bool(self.owner_action_required))}"
        return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]

    def as_dict(self) -> dict:
        return asdict(self)


def _conf_val(c) -> float:
    if isinstance(c, bool):                         # True/False confidence → 1.0/0.0
        return 1.0 if c else 0.0
    if isinstance(c, (int, float)):
        return float(c)
    return _CONF_TIER.get(str(c).upper().strip(), 0.0)


def _parse_ts(t) -> datetime:
    """FULL-FIDELITY parse (baked-in fix): keep microseconds + tz; naive assumed UTC; return UTC-aware."""
    dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_seconds(then_iso: str, now_iso: str) -> float | None:
    try:
        return (_parse_ts(now_iso) - _parse_ts(then_iso)).total_seconds()
    except Exception:
        return None                                 # unparseable → treat as "no known prior send"


class NotificationPolicy:
    """The single policy the emitters consult. should_notify() is pure (state injected); notify() is the
    one funnel that records dedup/cooldown and delegates the send to delivery.send_alert."""

    def __init__(self, *, store=None, now_fn=None, deliver_fn=None,
                 cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
                 min_confidence: float = DEFAULT_MIN_CONFIDENCE):
        self.store = store                          # injectable state; lazily defaulted in notify()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc).isoformat())
        self.deliver_fn = deliver_fn                # injectable sender; defaults to delivery.send_alert
        self.cooldown_seconds = cooldown_seconds
        self.min_confidence = min_confidence

    # ── pure decision (state + clock injected) ─────────────────────────────────────────────────────────
    def should_notify(self, event: NotificationEvent, *, state: dict | None = None,
                      now: str | None = None) -> tuple[bool, str]:
        state = state or {}
        now = now or self.now_fn()
        if event.category not in ALLOWED_REASONS:
            return (False, "routine")                                       # not one of the 7 → healthy/routine
        if not str(event.evidence_ref or "").strip():
            return (False, "no_evidence_ref")                              # §0 zero-fabrication: cite or drop
        if _conf_val(event.confidence) < self.min_confidence:
            return (False, "low_confidence")
        prior = state.get(event.key())
        if isinstance(prior, dict):
            if prior.get("hash") == event.content_hash():
                return (False, "unchanged")                                # same root, nothing changed
            age = _age_seconds(prior.get("sent_at", ""), now)
            if age is not None and age < self.cooldown_seconds:
                return (False, "duplicate_within_cooldown")
        return (True, event.category)

    # ── the ONE funnel ─────────────────────────────────────────────────────────────────────────────────
    def notify(self, event: NotificationEvent) -> dict:
        try:
            now = self.now_fn()
            if not event.created_at:
                event.created_at = now
            store = self.store if self.store is not None else DbNotificationStore()
            st = store.load() or {}
            notified = dict(st.get("notified") or {})
            ok, reason = self.should_notify(event, state=notified, now=now)
            if not ok:
                event.delivery_state = "SUPPRESSED"
                return {"notified": False, "reason": reason, "event": event.as_dict()}

            deliver_fn = self.deliver_fn
            if deliver_fn is None:
                from app.services.holding.delivery import send_alert
                deliver_fn = send_alert
            try:
                d = deliver_fn(_format(event)) or {}
            except Exception as e:
                d = {"delivered": False, "reason": f"send error: {str(e)[:80]}"}
            if d.get("delivered"):
                event.delivery_state = "SENT"
            elif "disabl" in str(d.get("reason", "")).lower():
                event.delivery_state = "DELIVERY_OFF"                       # opt-in default OFF, unchanged
            else:
                event.delivery_state = "NOT_DELIVERED"

            # record on DECISION, not on transport success (mirrors self_improvement_detect) so dedup/
            # cooldown hold even while delivery is opted OUT.
            notified[event.key()] = {"sent_at": now, "hash": event.content_hash(),
                                     "category": event.category}
            st["notified"] = _prune(notified, now)
            st["last_run"] = now
            store.save(st)
            return {"notified": True, "reason": reason, "delivered": d, "event": event.as_dict()}
        except Exception as e:
            return {"notified": False, "reason": f"notify error: {str(e)[:120]}",
                    "event": event.as_dict()}


def _format(event: NotificationEvent) -> str:
    scope = " · ".join(x for x in (event.company, event.mission) if x)
    head = f"[{event.severity}] {event.title}" + (f" ({scope})" if scope else "")
    lines = [head]
    if event.summary:
        lines.append(event.summary)
    if event.owner_action_required:
        lines.append("→ OWNER DECISION REQUIRED")
    lines.append(f"evidence: {event.evidence_ref} · reason: {event.category}")
    return "\n".join(lines)


def _prune(notified: dict, now_iso: str) -> dict:
    out = {}
    for k, v in notified.items():
        if not isinstance(v, dict):
            continue
        age = _age_seconds(v.get("sent_at", ""), now_iso)
        if age is None or age < _PRUNE_SECONDS:
            out[k] = v
    return out


# ── minimal notification-state store (single JSONB row; self-creating; fail-soft) — mirrors
#    self_improvement_detect.DbDetectionStore exactly (one shared store shape, not a new pattern). ────────
class DbNotificationStore:
    _DDL = ("CREATE TABLE IF NOT EXISTS holding_notification_state (id INT PRIMARY KEY DEFAULT 1, "
            "value JSONB NOT NULL DEFAULT '{}', updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")

    def _db(self):
        from app.database import SessionLocal
        return SessionLocal()

    def load(self) -> dict:
        from sqlalchemy import text
        import json
        try:
            db = self._db()
            try:
                db.execute(text(self._DDL))
                row = db.execute(text("SELECT value FROM holding_notification_state WHERE id=1")).fetchone()
                db.commit()
                v = row[0] if row else {}
                return v if isinstance(v, dict) else json.loads(v or "{}")
            finally:
                db.close()
        except Exception:
            return {}

    def save(self, value: dict) -> bool:
        from sqlalchemy import text
        import json
        try:
            db = self._db()
            try:
                db.execute(text(self._DDL))
                db.execute(text("INSERT INTO holding_notification_state (id, value, updated_at) "
                                "VALUES (1, :v, now()) ON CONFLICT (id) DO UPDATE SET value=:v, updated_at=now()"),
                           {"v": json.dumps(value)})
                db.commit()
                return True
            finally:
                db.close()
        except Exception:
            return False


class InMemoryNotificationStore:
    def __init__(self): self._v = {}
    def load(self) -> dict: return dict(self._v)
    def save(self, value: dict) -> bool: self._v = dict(value); return True


def demo() -> None:
    """Pure self-check (no DB/network). Proves: each of the 7 reasons fires; duplicate/unchanged/
    low-confidence/routine suppressed; a microsecond+tz timestamp computes the correct age; and
    delivery opt-in default OFF is preserved (send delegated, never bypassed)."""
    sent = []
    pol = NotificationPolicy(store=InMemoryNotificationStore(),
                             now_fn=lambda: "2026-09-03T12:00:00+00:00",
                             deliver_fn=lambda t: (sent.append(t) or {"delivered": True}))

    def ev(cat, **kw):
        base = dict(title=f"{cat} title", summary="s", severity="HIGH", evidence_ref=f"ref:{cat}",
                    confidence="HIGH", dedupe_key=f"k:{cat}")
        base.update(kw)
        return NotificationEvent(category=cat, **base)

    for i, cat in enumerate(sorted(ALLOWED_REASONS)):
        # unique clock per reason so none collide on cooldown
        pol.now_fn = (lambda c=cat: f"2026-09-03T1{sorted(ALLOWED_REASONS).index(c)}:00:00+00:00")
        r = pol.notify(ev(cat))
        assert r["notified"] is True and r["reason"] == cat, r
    assert len(sent) == 7, sent

    # duplicate: same dedupe_key, DIFFERENT content, within cooldown → suppressed
    pol.now_fn = lambda: "2026-09-03T12:00:00+00:00"
    st = InMemoryNotificationStore()
    p2 = NotificationPolicy(store=st, now_fn=lambda: "2026-09-03T12:00:00+00:00",
                            deliver_fn=lambda t: {"delivered": True})
    assert p2.notify(ev(SECURITY_FINDING, title="A"))["notified"] is True
    p2.now_fn = lambda: "2026-09-03T13:00:00+00:00"                       # +1h < 6h cooldown
    dup = p2.notify(ev(SECURITY_FINDING, title="B"))                     # different content, same key
    assert dup["notified"] is False and dup["reason"] == "duplicate_within_cooldown", dup

    # unchanged: same dedupe_key, SAME content → suppressed regardless of time
    p2.now_fn = lambda: "2026-09-04T23:00:00+00:00"                       # >cooldown, still unchanged
    unc = p2.notify(ev(SECURITY_FINDING, title="A"))
    assert unc["notified"] is False and unc["reason"] == "unchanged", unc

    # low-confidence + routine suppressed
    assert p2.notify(ev(HIGH_VALUE_OPPORTUNITY, confidence="LOW", dedupe_key="lc"))["reason"] == "low_confidence"
    assert p2.notify(NotificationEvent(category="routine_health_ok", title="all green",
                                       evidence_ref="probe:1"))["reason"] == "routine"
    # zero-fabrication: no evidence_ref → suppressed
    assert p2.notify(ev(REQUIRED_DECISION, evidence_ref="", dedupe_key="ne"))["reason"] == "no_evidence_ref"

    # BAKED-IN: microsecond + non-UTC offset timestamps compute the correct age (no tz drop / no [:26])
    a = "2026-09-03T12:00:00.123456+02:00"      # == 10:00:00.123456Z
    b = "2026-09-03T11:30:00.000000+00:00"      # == 11:30:00Z  → 90 min later
    age = _age_seconds(a, b)
    assert abs(age - (90 * 60 - 0.123456)) < 1e-3, age                    # 5399.876544s, tz honored

    # delivery opt-in default OFF preserved: with the REAL sender and the flag off, it's a no-op that the
    # funnel records as DELIVERY_OFF (we delegate to delivery.send_alert, never bypass it).
    p3 = NotificationPolicy(store=InMemoryNotificationStore(), now_fn=lambda: "2026-09-03T12:00:00+00:00")
    r3 = p3.notify(ev(MISSION_COMPLETION, dedupe_key="mc"))               # deliver_fn=None → real send_alert
    assert r3["notified"] is True and r3["event"]["delivery_state"] == "DELIVERY_OFF", r3
    print("notification_policy.demo OK — 7 reasons fire; routine/duplicate/unchanged/low-conf/no-evidence "
          "suppressed; tz-full-fidelity age; delivery default OFF preserved")


if __name__ == "__main__":
    demo()
