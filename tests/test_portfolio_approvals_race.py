from __future__ import annotations

import threading

from core.portfolio import state
from core.portfolio.actions import Action, ActionClass


def _action(i):
    return Action(f"verb{i}", "agent", ActionClass.AMBER, [], "n8n", {"i": i})


def test_concurrent_queue_and_resolve_lose_no_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    tmp_path.mkdir(parents=True, exist_ok=True)
    # Seed some approvals to resolve, and queue more concurrently.
    seeded = [state.queue_approval(_action(i)) for i in range(20)]

    errors = []

    def queuer(i):
        try:
            state.queue_approval(_action(1000 + i))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    def resolver(aid):
        try:
            state.resolve_approval(aid, "approved")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=queuer, args=(i,)) for i in range(30)]
    threads += [threading.Thread(target=resolver, args=(aid,)) for aid in seeded]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    all_ids = {a["id"] for a in state.list_approvals()}
    # All 20 seeded + 30 newly-queued ids must survive (no lost appends).
    assert len(all_ids) == 50
    approved = {a["id"] for a in state.list_approvals("approved")}
    assert set(seeded) == approved  # every seeded approval got resolved
