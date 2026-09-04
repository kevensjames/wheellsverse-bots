"""§31 single-NotificationPolicy guard. Run (from backend/):
    python3 -m app.services.holding.test_notification_policy

Mirrors test_registry.py: a flat ck() ledger. Proves the ONE funnel fires on exactly the 7 allowed
reasons, suppresses routine/duplicate/unchanged/low-confidence/no-evidence, records dedup/cooldown in an
injectable store, keeps delivery opt-in default OFF (delegates to delivery.send_alert, never bypasses),
and computes timestamp age at FULL fidelity (microseconds + tz preserved — the baked-in prior-pass fix).
"""
from app.services.holding.notification_policy import (
    NotificationPolicy, NotificationEvent, InMemoryNotificationStore, ALLOWED_REASONS, _age_seconds,
    CRITICAL_MATERIAL_CHANGE, HIGH_VALUE_OPPORTUNITY, REQUIRED_DECISION, MISSION_COMPLETION,
    REPEATED_FAILURE, SECURITY_FINDING, SCHEDULED_EXECUTIVE_BRIEF, DEFAULT_COOLDOWN_SECONDS)

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


def _ev(cat, **kw):
    base = dict(title=f"{cat} title", summary="s", severity="HIGH", evidence_ref=f"ref:{cat}",
                confidence="HIGH", dedupe_key=f"k:{cat}")
    base.update(kw)
    return NotificationEvent(category=cat, **base)


# ── 1. each of the 7 allowed reasons fires exactly once (distinct clock so none collide on cooldown) ────
SEVEN = [CRITICAL_MATERIAL_CHANGE, HIGH_VALUE_OPPORTUNITY, REQUIRED_DECISION, MISSION_COMPLETION,
         REPEATED_FAILURE, SECURITY_FINDING, SCHEDULED_EXECUTIVE_BRIEF]
ck("exactly 7 allowed reasons defined", set(SEVEN) == set(ALLOWED_REASONS) and len(SEVEN) == 7)

sent = []
store = InMemoryNotificationStore()
fired_reasons = []
for i, cat in enumerate(SEVEN):
    pol = NotificationPolicy(store=store, now_fn=(lambda h=i: f"2026-09-03T0{h}:00:00+00:00"),
                             deliver_fn=lambda t: (sent.append(t) or {"delivered": True}))
    r = pol.notify(_ev(cat))
    fired_reasons.append((cat, r.get("notified"), r.get("reason")))
ck("all 7 allowed reasons fire (notified=True, reason=category)",
   all(n is True and rz == c for (c, n, rz) in fired_reasons))
ck("the sender was invoked once per fired reason (single funnel)", len(sent) == 7)
ev0 = NotificationEvent(category=SECURITY_FINDING, title="t", evidence_ref="e")
ck("event carries the full §31 field set", all(hasattr(ev0, f) for f in (
   "event_id", "category", "severity", "company", "mission", "title", "summary", "evidence_ref",
   "owner_action_required", "created_at", "dedupe_key", "delivery_state", "confidence")))

# ── 2. duplicate (same dedupe_key) within cooldown → suppressed ─────────────────────────────────────────
st2 = InMemoryNotificationStore()
p = NotificationPolicy(store=st2, now_fn=lambda: "2026-09-03T12:00:00+00:00",
                       deliver_fn=lambda t: {"delivered": True})
first = p.notify(_ev(SECURITY_FINDING, title="A"))
p.now_fn = lambda: "2026-09-03T13:00:00+00:00"                      # +1h, well inside the 6h cooldown
dup = p.notify(_ev(SECURITY_FINDING, title="B"))                    # same dedupe_key, DIFFERENT content
ck("first send of a key notifies", first["notified"] is True)
ck("duplicate (same dedupe_key) within cooldown suppressed", dup["notified"] is False
   and dup["reason"] == "duplicate_within_cooldown")

# ── 3. unchanged (same key, same content) → suppressed even past cooldown ───────────────────────────────
p.now_fn = lambda: "2026-09-05T00:00:00+00:00"                      # >>cooldown but content identical
unc = p.notify(_ev(SECURITY_FINDING, title="A"))
ck("unchanged (same key + same content) suppressed", unc["notified"] is False and unc["reason"] == "unchanged")

# ── 4. low-confidence → suppressed ─────────────────────────────────────────────────────────────────────
lc = p.notify(_ev(HIGH_VALUE_OPPORTUNITY, confidence="LOW", dedupe_key="lc"))
lcf = p.notify(_ev(HIGH_VALUE_OPPORTUNITY, confidence=0.2, dedupe_key="lcf"))
ck("low-confidence (tier LOW) suppressed", lc["notified"] is False and lc["reason"] == "low_confidence")
ck("low-confidence (float 0.2) suppressed", lcf["notified"] is False and lcf["reason"] == "low_confidence")

# ── 5. routine / healthy (not one of the 7) → no notify ────────────────────────────────────────────────
rout = p.notify(NotificationEvent(category="routine_health_ok", title="all systems green",
                                  evidence_ref="probe:1", confidence="HIGH"))
ck("routine/healthy category → not notified", rout["notified"] is False and rout["reason"] == "routine")

# ── 6. zero-fabrication: an allowed reason with NO evidence_ref → suppressed ────────────────────────────
ne = p.notify(_ev(REQUIRED_DECISION, evidence_ref="", dedupe_key="ne"))
ck("no evidence_ref → suppressed (zero-fabrication)", ne["notified"] is False and ne["reason"] == "no_evidence_ref")

# ── 7. BAKED-IN: microsecond + non-UTC offset timestamps compute the correct age (no tz drop, no [:26]) ─
a = "2026-09-03T12:00:00.123456+02:00"     # == 2026-09-03T10:00:00.123456Z
b = "2026-09-03T11:30:00.000000+00:00"     # == 11:30:00Z → 90 min after `a`
age = _age_seconds(a, b)
ck("tz-aware microsecond age is exact (tz honored, microseconds kept)",
   age is not None and abs(age - (90 * 60 - 0.123456)) < 1e-3)
# the OLD truncating pattern would have dropped +02:00 and read a as 12:00 → NEGATIVE age; prove we don't
ck("age is positive (offset not silently dropped)", age > 0)
# naive timestamp is assumed UTC (not rejected)
ck("naive timestamp assumed UTC", _age_seconds("2026-09-03T11:00:00", "2026-09-03T12:00:00") == 3600.0)

# ── 8. delivery opt-in default OFF preserved — funnel delegates to delivery.send_alert, never bypasses ──
p3 = NotificationPolicy(store=InMemoryNotificationStore(), now_fn=lambda: "2026-09-03T12:00:00+00:00")
r3 = p3.notify(_ev(MISSION_COMPLETION, dedupe_key="mc"))            # deliver_fn=None → real send_alert
ck("delivery default OFF: decided-notified but transport is a no-op (DELIVERY_OFF)",
   r3["notified"] is True and r3["event"]["delivery_state"] == "DELIVERY_OFF")
ck("no channel/opt-in → send_alert reported not delivered", r3["delivered"].get("delivered") is False)

# ── 9. dedup is RECORDED on decision (mirrors self_improvement_detect) so it holds even when delivery OFF ─
st9 = InMemoryNotificationStore()
p9 = NotificationPolicy(store=st9, now_fn=lambda: "2026-09-03T12:00:00+00:00")   # delivery off (real sender)
p9.notify(_ev(REPEATED_FAILURE, dedupe_key="rf"))
again = p9.notify(_ev(REPEATED_FAILURE, dedupe_key="rf"))                        # identical → unchanged
ck("dedup recorded despite delivery OFF (2nd identical suppressed as unchanged)",
   again["notified"] is False and again["reason"] == "unchanged")
ck("cooldown constant is a real window", DEFAULT_COOLDOWN_SECONDS >= 3600)

n = len(res); ok = sum(res)
print(f"\nNOTIFICATION POLICY TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
