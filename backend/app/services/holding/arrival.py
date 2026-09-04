"""§12/§84 owner arrival — a durable per-principal last-visit store + changes-since-last-visit + a single
greeting per meaningful session.

changes_since_last_visit is computed from AUTHORITATIVE, timestamped events — the governance audit log
(governance.audit_log.list_actions), NOT conversation memory. Only real, cited audit rows are reported; an
unparseable or missing timestamp contributes nothing (never a fabricated change). On the very first visit
there is honestly no baseline to compare (no fake "great progress").

One greeting per MEANINGFUL session: dedupe is by ``session_id``. A refresh / nav / reconnect that carries
the SAME session_id is silent (greet=False, store untouched); a genuinely-new session greets once and
advances the store. This mirrors §125 (greeting dedupe) and §66 (arrival reads the authenticated session,
not facial-id).

Reuses briefing.today_for_you for the owner-facing sections — the changes since last visit ARE the
``kai_completed_since_last_visit`` feed today_for_you already exposes; no parallel brief builder.

BAKED-IN fix (prior-pass review): timestamps are parsed FULL-FIDELITY (microseconds + tz preserved, naive
assumed UTC) before comparison — the same fix baked into notification_policy — so an event stamped in a
non-UTC offset is compared correctly and never silently mis-ordered.

Store is injectable (DB or in-memory), so the whole module is a plain python3 self-test (mirrors
holding_problems.demo). Run: python3 -m app.services.holding.test_arrival
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.holding.briefing import today_for_you


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(t):
    """FULL-FIDELITY parse (baked-in fix): keep microseconds + tz; naive assumed UTC; None on failure."""
    try:
        dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _default_events(limit: int) -> list:
    """The AUTHORITATIVE event source: the governance audit log (timestamped, append-only). Fail-open."""
    try:
        from app.services.governance.audit_log import list_actions
        return list_actions(limit=limit)
    except Exception:
        return []


def changes_since_last_visit(since, *, events=None, now: str = "", limit: int = 200) -> dict:
    """Real governed changes recorded since ``since`` (an ISO timestamp), from the AUTHORITATIVE audit log
    (or an injected ``events`` list of audit rows). Zero-fabrication: only rows with a parseable ts strictly
    AFTER ``since`` are reported; each is cited (action/scope/actor/success/id). ``since`` None/empty → an
    honest baseline (no prior visit to compare). Newest-first."""
    evs = events if events is not None else _default_events(limit)
    if not since:
        return {"baseline": True, "since": None, "count": 0, "changes": [],
                "note": "first recorded visit — establishing a baseline from here; no prior visit to compare"}
    since_dt = _parse_ts(since)
    rows: list = []
    if since_dt is not None:
        for e in evs or []:
            ts = e.get("ts") or e.get("at") or e.get("timestamp")
            edt = _parse_ts(ts)
            if edt is None or edt <= since_dt:
                continue                       # unparseable or not-after-last-visit → not a change (never faked)
            rows.append((edt, {"at": ts, "action": e.get("action") or e.get("type"), "scope": e.get("scope"),
                               "actor": e.get("actor"), "success": e.get("success"), "id": e.get("id")}))
    rows.sort(key=lambda r: r[0], reverse=True)          # newest first, by the TRUE UTC instant (tz-correct)
    out = [r[1] for r in rows]
    return {"baseline": False, "since": since, "count": len(out), "changes": out[:limit]}


def _greeting(changes: dict) -> str:
    """Honest greeting — states real facts, NO fake optimism ('great progress', 'all good')."""
    if changes.get("baseline"):
        return ("Welcome. This is your first recorded visit — I'm establishing a baseline from here; "
                "there is no prior visit to compare against yet.")
    n = changes.get("count", 0)
    since = changes.get("since")
    if n == 0:
        return f"Welcome back. No governed actions were recorded since your last visit ({since})."
    return f"Welcome back. {n} governed action(s) recorded since your last visit ({since})."


def arrival(principal: str, session_id: str, *, store=None, events=None, now: str = "",
            owner_actions=None, kai_working_now=None, material_changes=None, risks=None,
            watching=None) -> dict:
    """§12/§84 arrival. One greeting per MEANINGFUL session (dedupe by session_id): a repeat of the same
    session_id (refresh/nav/reconnect) is silent and does NOT advance the store. A new session greets once,
    computes changes since the last visit from the AUTHORITATIVE audit log, composes the owner-facing brief
    via briefing.today_for_you (the changes ARE kai_completed_since_last_visit), then records this visit.
    Never raises fatally."""
    try:
        principal = (principal or "").strip() or "unknown"
        session_id = (session_id or "").strip()
        st = store if store is not None else DbLastVisitStore()
        now = now or _now()
        prior = st.get(principal) or {}
        last_session = prior.get("last_session_id")
        last_visit = prior.get("last_visit_at")

        # dedupe: same meaningful session → silent (no greeting, store untouched).
        if session_id and last_session and session_id == last_session:
            return {"greet": False, "reason": "same_session", "principal": principal,
                    "session_id": session_id, "last_visit_at": last_visit}

        changes = changes_since_last_visit(last_visit, events=events, now=now)
        brief = today_for_you(owner_actions=owner_actions, kai_completed=changes["changes"],
                              kai_working_now=kai_working_now, material_changes=material_changes,
                              risks=risks, watching=watching)
        st.set(principal, now, session_id)     # record THIS meaningful session (advances the store)
        return {"greet": True, "reason": "first_visit" if not last_session else "new_session",
                "principal": principal, "session_id": session_id,
                "last_visit_at": last_visit, "this_visit_at": now,
                "greeting": _greeting(changes), "changes_since_last_visit": changes, "today": brief}
    except Exception as e:
        return {"greet": False, "reason": f"arrival error: {str(e)[:120]}",
                "principal": principal, "session_id": session_id}


# ── durable per-principal last-visit store (self-creating table; fail-soft) — mirrors the
#    notification_policy DbNotificationStore shape (one shared store idiom, not a new pattern). ──────────
class DbLastVisitStore:
    _DDL = ("CREATE TABLE IF NOT EXISTS holding_last_visit (principal TEXT PRIMARY KEY, "
            "last_visit_at TIMESTAMPTZ, last_session_id TEXT, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")

    def _db(self):
        from app.database import SessionLocal
        return SessionLocal()

    def get(self, principal: str) -> dict:
        from sqlalchemy import text
        try:
            db = self._db()
            try:
                db.execute(text(self._DDL))
                row = db.execute(text("SELECT last_visit_at, last_session_id FROM holding_last_visit "
                                      "WHERE principal = :p"), {"p": principal}).fetchone()
                db.commit()
                if not row:
                    return {}
                return {"last_visit_at": (row[0].isoformat() if hasattr(row[0], "isoformat") else row[0]),
                        "last_session_id": row[1]}
            finally:
                db.close()
        except Exception:
            return {}

    def set(self, principal: str, visit_at: str, session_id: str) -> bool:
        from sqlalchemy import text
        try:
            db = self._db()
            try:
                db.execute(text(self._DDL))
                db.execute(text(
                    "INSERT INTO holding_last_visit (principal, last_visit_at, last_session_id, updated_at) "
                    "VALUES (:p, CAST(:v AS TIMESTAMPTZ), :s, now()) "
                    "ON CONFLICT (principal) DO UPDATE SET last_visit_at = CAST(:v AS TIMESTAMPTZ), "
                    "last_session_id = :s, updated_at = now()"),
                    {"p": principal, "v": visit_at, "s": session_id})
                db.commit()
                return True
            finally:
                db.close()
        except Exception:
            return False


class InMemoryLastVisitStore:
    def __init__(self):
        self._v: dict = {}

    def get(self, principal: str) -> dict:
        return dict(self._v.get(principal) or {})

    def set(self, principal: str, visit_at: str, session_id: str) -> bool:
        self._v[principal] = {"last_visit_at": visit_at, "last_session_id": session_id}
        return True


def demo() -> None:
    """Pure self-check (no DB/network). Proves: first visit is a baseline (no fake optimism); a new session
    greets once and computes changes from AUTHORITATIVE audit events; the SAME session_id (refresh) is
    silent and does not advance the store; a later session sees only events AFTER the prior visit; a
    non-UTC-offset event ts is compared at full fidelity."""
    store = InMemoryLastVisitStore()
    audit = [
        {"id": "a1", "ts": "2026-09-01T10:00:00+00:00", "action": "holding.run_cycle", "scope": "kai:ultra",
         "actor": "kai-auto", "success": True},
        {"id": "a2", "ts": "2026-09-02T12:30:00+02:00", "action": "proposal.approved", "scope": "kai:ultra",
         "actor": "operator", "success": True},   # == 10:30Z on the 2nd
        {"id": "a3", "ts": "not-a-date", "action": "broken", "scope": "x", "actor": "y", "success": True},
    ]

    # 1. first visit → baseline greeting, no changes, no fake optimism
    r1 = arrival("operator", "sess-1", store=store, events=audit, now="2026-09-01T09:00:00+00:00")
    assert r1["greet"] is True and r1["reason"] == "first_visit", r1
    assert r1["changes_since_last_visit"]["baseline"] is True and r1["changes_since_last_visit"]["count"] == 0
    for banned in ("great", "progress", "all good", "on track"):
        assert banned not in r1["greeting"].lower(), r1["greeting"]

    # 2. same session_id (refresh/nav/reconnect) → SILENT, store not advanced
    r2 = arrival("operator", "sess-1", store=store, events=audit, now="2026-09-01T09:05:00+00:00")
    assert r2["greet"] is False and r2["reason"] == "same_session", r2
    assert store.get("operator")["last_visit_at"] == "2026-09-01T09:00:00+00:00", "refresh must not advance"

    # 3. a NEW session → greets once, computes changes from the audit log strictly AFTER the last visit
    r3 = arrival("operator", "sess-2", store=store, events=audit, now="2026-09-03T08:00:00+00:00")
    assert r3["greet"] is True and r3["reason"] == "new_session", r3
    ch = r3["changes_since_last_visit"]
    ids = {c["id"] for c in ch["changes"]}
    assert ids == {"a1", "a2"}, ids                  # both real events after 09-01T09:00; the bad-ts row dropped
    assert ch["changes"][0]["id"] == "a2", "newest-first"     # a2 (10:30Z 09-02) newer than a1 (10:00Z 09-01)
    assert "2" in r3["greeting"] and "fabricat" not in r3["greeting"].lower()
    # today_for_you reuse: the changes ARE the kai_completed_since_last_visit feed
    assert r3["today"]["kai_completed_since_last_visit"] == ch["changes"], r3["today"]

    # 4. after advancing to sess-2 @ 09-03T08:00, a later session sees NOTHING new (all events precede it)
    r4 = arrival("operator", "sess-3", store=store, events=audit, now="2026-09-04T08:00:00+00:00")
    assert r4["greet"] is True and r4["changes_since_last_visit"]["count"] == 0, r4
    assert "No governed actions" in r4["greeting"], r4["greeting"]

    # 5. full-fidelity tz: an event at +02:00 is compared in UTC (the a2 10:30Z row is AFTER a 09-02T09:00Z visit)
    s2 = InMemoryLastVisitStore()
    s2.set("op2", "2026-09-02T09:00:00+00:00", "old")
    r5 = arrival("op2", "sess-x", store=s2, events=audit, now="2026-09-03T00:00:00+00:00")
    assert {c["id"] for c in r5["changes_since_last_visit"]["changes"]} == {"a2"}, r5["changes_since_last_visit"]

    print("arrival.demo OK — first-visit baseline (no fake optimism); refresh silent + store not advanced; "
          "new session greets once w/ changes from the authoritative audit log; bad-ts dropped; tz full-fidelity")


if __name__ == "__main__":
    demo()
