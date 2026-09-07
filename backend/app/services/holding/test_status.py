"""status.autonomy_status honesty guard (review L2): MONEY_MODE and financial_execution come from the ONE readers
(self_model._flags / brakes._financial_row), never from literals. Zero-framework (mirrors test_brakes.py).
DB-down is simulated by patching status.SessionLocal to raise — on this machine the 'dummy' DSN is answered by a
trust-auth local Postgres, so a DSN alone is NOT DB-less. Run (from backend/):
    python3 -m app.services.holding.test_status
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding import status as st                  # noqa: E402
from app.services.holding.self_model import _flags             # noqa: E402

FIN_KEYS = ("KAI_SCOPE_SOL_TRANSFER", "KAI_SCOPE_SOL", "DWOLLA_KEY", "DWOLLA_SECRET", "DWOLLA_ENV", "DWOLLA_ALLOW_PRODUCTION")


def fin_env(**kv):
    """os.environ with ONLY the given Sol/Dwolla switches set (same helper shape as test_brakes.fin_env)."""
    env = {k: v for k, v in os.environ.items() if k not in FIN_KEYS}
    env.update(kv)
    return patch.dict(os.environ, env, clear=True)


def _db_down(*_a, **_k):
    raise RuntimeError("db down")


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    with patch.object(st, "SessionLocal", _db_down), fin_env():
        off = st.autonomy_status()
    with patch.object(st, "SessionLocal", _db_down), fin_env(KAI_SCOPE_SOL_TRANSFER="1", DWOLLA_KEY="k-SECRET", DWOLLA_SECRET="s-SECRET"):
        on = st.autonomy_status()
    with patch.object(st, "SessionLocal", _db_down), fin_env(), \
            patch("app.services.dwolla.client.is_configured", side_effect=RuntimeError("reader down")):
        unr = st.autonomy_status()
    with patch.object(st, "SessionLocal", _db_down), fin_env(), \
            patch("app.services.holding.self_model._flags", return_value={"MONEY_MODE": "MOCK"}):
        declared = st.autonomy_status()

    ck("DB down -> worker plane DEGRADED, overall DEGRADED, cron last_run PENDING (no fabricated liveness)",
       off["overall"] == "DEGRADED" and off["checks"]["WORKER_PLANE"] == "DEGRADED" and off["checks"]["WATCHING"] == "PENDING")
    ck("L2: nothing injected -> financial_execution OFF from brakes._financial_row (scope off + creds absent) — never a literal DISABLED",
       off["financial_execution"] == "OFF")
    ck("L2: KAI_SCOPE_SOL_TRANSFER=1 + Dwolla creds injected -> financial_execution ON — NOT 'DISABLED' (a hardcoded literal could never report this)",
       on["financial_execution"] == "ON" and on["financial_execution"] != "DISABLED")
    ck("L2: scope/dwolla readers unreadable -> financial_execution UNAVAILABLE (never a guessed OFF / DISABLED)",
       unr["financial_execution"] == "UNAVAILABLE")
    ck("L2: MONEY_MODE is self_model._flags()['MONEY_MODE'] — undeclared in this app's Settings (None live) -> 'UNAVAILABLE', never a literal MOCK",
       _flags()["MONEY_MODE"] is None and off["checks"]["MONEY_MODE"] == "UNAVAILABLE" and on["checks"]["MONEY_MODE"] == "UNAVAILABLE")
    ck("L2: a DECLARED MONEY_MODE is reported as declared (MOCK)", declared["checks"]["MONEY_MODE"] == "MOCK")
    ck("no secret value leaks into the roll-up", "SECRET" not in str(on))
    src = Path(st.__file__).read_text()
    ck("static: status.py writes neither literal 'MOCK' nor 'DISABLED' — both rows are derived, not asserted",
       '"MOCK"' not in src and "'MOCK'" not in src and '"DISABLED"' not in src and "'DISABLED'" not in src)

    n = len(res); ok = sum(res)
    print(f"\nSTATUS (autonomy_status honesty) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
