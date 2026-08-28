"""Regression for the Pass-4 adversarial finding: a FAILED governed LLM call must
retain its llm_call_log evidence even though the request transaction is rolled back
on the terminal-failure path (get_db closes without commit).

The fix: Router._log_failure_safe writes on an ISOLATED short-lived SessionLocal that
commits immediately — never the shared request Session (which is rolled back). This
test asserts that invariant without a live DB by patching SessionLocal to a fake, and
proves: (1) a fresh session is opened, (2) commit() is called on it, (3) close() is
called, (4) the shared request session (self.spend.session) is NOT used.

Run: python3 backend/app/services/router/test_failure_log_durable.py
"""
import sys, os
# NB: run from repo root, not this dir — a sibling module here is named types.py and
# would shadow stdlib `types`. We insert the repo root and never import stdlib types.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class _NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeSession:
    def __init__(self): self.committed = False; self.closed = False; self.executed = 0
    def execute(self, *a, **k): self.executed += 1
    def commit(self): self.committed = True
    def close(self): self.closed = True


class _FakeAdapter:
    name = "ollama"; model = "llama3.1:8b"


def test_failure_log_uses_isolated_committed_session(monkeypatch=None):
    # import lazily so a missing App B dep doesn't break collection elsewhere
    from app.services.router.router import Router
    import app.database as dbmod

    fresh = _FakeSession()
    # The SHARED request-session tracker — _log_failure_safe must NEVER touch this
    # (its transaction is the one being rolled back); wire it to blow up if it does.
    shared = _NS(session=_FakeSession(),
                 log_call=lambda **k: (_ for _ in ()).throw(AssertionError("used the shared request session")))

    # patch the SessionLocal that _log_failure_safe imports from app.database
    orig = dbmod.SessionLocal
    dbmod.SessionLocal = lambda: fresh
    try:
        # call the method unbound with a bare mock self so we don't build a full
        # Router (heavy deps). .spend is present only to prove it is left alone.
        me = _NS(spend=shared)
        Router._log_failure_safe(me, user_id="u1", adapter=_FakeAdapter(), error="boom")
    finally:
        dbmod.SessionLocal = orig

    assert fresh.executed >= 1, "failure row was not written on the isolated session"
    assert fresh.committed, "isolated session was NOT committed — failure evidence would be lost on rollback"
    assert fresh.closed, "isolated session was not closed"
    assert not shared.session.committed, "must not commit on the shared request session"


if __name__ == "__main__":
    test_failure_log_uses_isolated_committed_session()
    print("  ✓ test_failure_log_uses_isolated_committed_session")
    print("\n1/1 durable-failure-log regression passed")
