"""Phase 9 defect tests: KAI_CAPABILITY_EXECUTION_ENABLED must be a feature flip.

Before this repair, turning the flag on raised ImportError at startup because
`app.routers.admin_capabilities` never landed on this lineage -- an outage, not a
feature. These tests pin the behaviour in all three states, and pin the route topology
so execution can never quietly appear on the read-only catalog surface.

Self-running script (repo convention for capability tests):
    cd backend && python3 app/routers/test_capability_routes.py
"""
from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATABASE_URL", "sqlite:///./_kai_caproutes_test.db")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-only")
os.environ.setdefault("SESSION_SIGNING_SECRET", "test-only")
os.environ.setdefault("API_KEY", "test-only")

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(f"  {'ok ' if cond else 'FAIL'} {name}" + (f"  ({detail})" if detail and not cond else ""))


def build_app(flag: bool, break_import: bool = False):
    """Rebuild app.main with the flag in a given state.

    Modules are purged so main.py's guarded block is re-executed rather than reusing a
    cached import from a previous state.
    """
    os.environ["KAI_CAPABILITY_EXECUTION_ENABLED"] = "true" if flag else "false"
    for mod in [m for m in list(sys.modules)
                if m.startswith("app.main") or m.startswith("app.config")
                or m.startswith("app.routers.admin_capabilities")]:
        del sys.modules[mod]
    # Purging sys.modules is not enough: `from app.routers import admin_capabilities`
    # resolves the PARENT PACKAGE ATTRIBUTE first and only falls through to sys.meta_path
    # when it is absent. Leaving the attribute set meant the blocker below was never
    # consulted and the "missing module" case silently tested the working one.
    routers_pkg = sys.modules.get("app.routers")
    if routers_pkg is not None and hasattr(routers_pkg, "admin_capabilities"):
        delattr(routers_pkg, "admin_capabilities")

    class _Blocker:
        """Simulate the exact defect: the router module cannot be imported."""
        def find_module(self, fullname, path=None):
            return self if fullname == "app.routers.admin_capabilities" else None

        def find_spec(self, fullname, path=None, target=None):
            if fullname == "app.routers.admin_capabilities":
                raise ImportError("simulated missing router module")
            return None

    blocker = _Blocker()
    if break_import:
        sys.meta_path.insert(0, blocker)
    try:
        main = importlib.import_module("app.main")
        return main
    finally:
        if break_import and blocker in sys.meta_path:
            sys.meta_path.remove(blocker)


def paths_methods(app, prefix):
    out = []
    for r in app.routes:
        p = getattr(r, "path", "")
        if p.startswith(prefix):
            out.append((p, tuple(sorted(getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}))))
    return out


print("=== 1. DISABLED mode stays healthy with zero new surface ===")
m = build_app(flag=False)
body = m.health()
check("app boots with flag off", True)
check("health status ok", body["status"] == "ok", body)
check("capability_execution reported DISABLED",
      body["subsystems"]["capability_execution"]["state"] == "DISABLED", body)
check("no /admin/capabilities routes exist", not paths_methods(m.app, "/admin/capabilities"))
check("no /admin/capability-exec routes exist", not paths_methods(m.app, "/admin/capability-exec"))

print("\n=== 2. ENABLED mode starts successfully (the defect) ===")
m = build_app(flag=True)
body = m.health()
check("app boots with flag on (no ImportError)", True)
check("health status ok", body["status"] == "ok", body)
check("capability_execution reported READY",
      body["subsystems"]["capability_execution"]["state"] == "READY", body)
cat = paths_methods(m.app, "/admin/capabilities")
ex = paths_methods(m.app, "/admin/capability-exec")
check("catalog routes present", len(cat) >= 3, cat)
check("execution routes present", len(ex) >= 3, ex)

print("\n=== 3. Catalog surface is GET-only; execution is a SEPARATE surface ===")
non_get = [(p, mm) for p, mm in cat if set(mm) - {"GET"}]
check("every /admin/capabilities route is GET-only", not non_get, non_get)
non_post = [(p, mm) for p, mm in ex if set(mm) - {"POST"}]
check("every /admin/capability-exec route is POST-only", not non_post, non_post)
check("execution does not share the catalog prefix",
      all(not p.startswith("/admin/capabilities") for p, _ in ex), ex)

print("\n=== 4. Authorization is enforced on BOTH surfaces ===")
from app.routers import admin_capabilities as ac  # noqa: E402
from app.routers.admin_chat import require_kai_ultra  # noqa: E402

def gated(router):
    return any(getattr(d, "dependency", None) is require_kai_ultra
               for d in getattr(router, "dependencies", []))

check("catalog router requires owner (require_kai_ultra)", gated(ac.router))
check("execution router requires owner (require_kai_ultra)", gated(ac.exec_router))
check("both surfaces use the SAME gate (no parallel auth)",
      gated(ac.router) and gated(ac.exec_router))

print("\n=== 5. No raw provider/command passthrough ===")
fields = set(ac.InvokeBody.model_fields)
forbidden = {"command", "shell", "cmd", "argv", "args", "entrypoint", "env", "cwd",
             "url", "provider", "endpoint", "base_url", "api_key"}
check("invoke body exposes no command/provider fields", not (fields & forbidden),
      sorted(fields & forbidden))
check("invoke body ignores unmodelled fields",
      ac.InvokeBody.model_config.get("extra") == "ignore")
# A caller-supplied role/scope must not become authority.
p = ac._owner()
check("principal is server-derived (owner, no caller scopes)",
      p.role == "owner" and not p.scopes)
from app.services.capability.execution import OPERATIONS  # noqa: E402
check("operations resolve through a server-owned allowlist", isinstance(OPERATIONS, dict) and OPERATIONS)

print("\n=== 6. A broken subsystem degrades readiness truthfully (no outage) ===")
m = build_app(flag=True, break_import=True)
body = m.health()
check("app still boots when the router module is missing", True)
check("health reports degraded", body["status"] == "degraded", body)
sub = body["subsystems"]["capability_execution"]
check("subsystem reported UNAVAILABLE", sub["state"] == "UNAVAILABLE", sub)
check("failure reason is surfaced", "reason" in sub and "ImportError" in sub["reason"], sub)
check("no capability routes were mounted", not paths_methods(m.app, "/admin/capabilit"))

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
sys.exit(1 if FAILED else 0)
