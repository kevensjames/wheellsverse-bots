"""Missing authentication configuration must fail CLOSED.

THE DEFECT. Both App A gates open completely when `API_KEY` is unset:

    core/api.py:235   verify_api_key      ->  if not _API_KEY: return
    core/api.py:266   require_admin_json  ->  if not _API_KEY: return

`_API_KEY` is read once at import, so this is a whole-process property fixed at boot. An App A
redeploy or a key rotation that leaves the variable briefly unset silently un-gates the entire
owner `/api/*` surface AND every protected `/admin` JSON route — with no log, no warning, and no
difference an operator could observe. App A is deployed by CLI upload with hand-managed variables,
which is exactly the situation where a variable goes missing.

"No credential is configured" is not a reason to trust everyone. It is a reason to trust no one.

THE RULE THIS PINS. The absence of a credential opens nothing in a hosted environment. Local
development stays workable, but only when the environment SAYS it is local — never by inference from
a missing secret, because a missing secret is precisely the failure being defended against.

    APP_ENV development / local / dev / test   + no key  ->  open  (DEV_OPEN, local only)
    APP_ENV production / staging / prod / stage + no key ->  401   (MISCONFIGURED)
    APP_ENV unset or unrecognised              + no key  ->  401   (fail closed by default)
    any environment                            + key set ->  normal policy

Startup/readiness surfaces the misconfiguration so it is visible, but it does not return protected
content and it does not refuse to boot: turning a small config error into a total outage would be a
worse failure than the one being fixed.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")
os.environ.setdefault("RELEASE_VERIFIER_SIGNING_SECRET", "verifier-signing-secret")

from core import api as core_api                          # noqa: E402
from core import operator_session as osess                # noqa: E402
from core.operator_session_web import COOKIE_NAME         # noqa: E402

OWNER_KEY = os.environ["API_KEY"]
SESSION_SECRET = os.environ["SESSION_SIGNING_SECRET"]

# Protected surfaces on both gates. Each must be 401 for an anonymous caller when auth config is
# invalid — NOT 200-with-data, which is today's behaviour.
ADMIN_JSON = ["/admin/registry.json", "/admin/capabilities.json", "/admin/command/metrics.json"]
API_ROUTES = ["/api/bots", "/api/scheduler/jobs"]

HOSTED_ENVS = ["production", "staging", "prod", "stage", "PRODUCTION"]
DEV_ENVS = ["development", "local", "dev", "test"]
UNKNOWN_ENVS = ["", "qa", "preview", "banana", "prod-like"]


@pytest.fixture
def client():
    return TestClient(core_api.app)


@pytest.fixture
def no_key(monkeypatch):
    """The exact production hazard: the process booted with no API_KEY."""
    monkeypatch.setattr(core_api, "_API_KEY", "", raising=False)
    return monkeypatch


def _set_env(monkeypatch, app_env):
    monkeypatch.setattr(core_api, "_APP_ENV", app_env, raising=False)


# ── 1. hosted environment + no key must refuse ────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ADMIN_JSON)
@pytest.mark.parametrize("app_env", HOSTED_ENVS)
def test_admin_json_fails_closed_without_a_key_in_a_hosted_env(client, no_key, path, app_env):
    _set_env(no_key, app_env)
    r = client.get(path, headers={"Accept": "application/json"})
    assert r.status_code == 401, (
        f"{path} answered {r.status_code} anonymously with APP_ENV={app_env} and no API_KEY — "
        "a missing credential opened the admin surface")


@pytest.mark.parametrize("path", API_ROUTES)
@pytest.mark.parametrize("app_env", HOSTED_ENVS)
def test_api_surface_fails_closed_without_a_key_in_a_hosted_env(client, no_key, path, app_env):
    _set_env(no_key, app_env)
    r = client.get(path)
    assert r.status_code == 401, (
        f"{path} answered {r.status_code} anonymously with APP_ENV={app_env} and no API_KEY")


@pytest.mark.parametrize("app_env", UNKNOWN_ENVS)
def test_unknown_or_unset_environment_fails_closed(client, no_key, app_env):
    """The safe default. An environment the code does not recognise is treated as hosted, because
    guessing 'probably local' is how a production box ends up open."""
    _set_env(no_key, app_env)
    assert client.get("/admin/registry.json").status_code == 401
    assert client.get("/api/bots").status_code == 401


# ── 2. local development still works ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("app_env", DEV_ENVS)
def test_local_development_without_a_key_still_works(client, no_key, app_env):
    """Failing closed must not make the project undevelopable. A declared dev environment with no
    key keeps today's open behaviour — but it is declared, never inferred."""
    _set_env(no_key, app_env)
    r = client.get("/admin/registry.json", headers={"Accept": "application/json"})
    assert r.status_code == 200, f"local dev broke under APP_ENV={app_env}"


# ── 3. with a key configured, policy is unchanged ─────────────────────────────────────────────────
@pytest.mark.parametrize("app_env", HOSTED_ENVS + DEV_ENVS)
def test_configured_key_behaves_exactly_as_before(client, monkeypatch, app_env):
    _set_env(monkeypatch, app_env)
    assert client.get("/admin/registry.json").status_code == 401
    assert client.get("/admin/registry.json",
                      headers={"X-API-Key": OWNER_KEY}).status_code == 200
    assert client.get("/admin/registry.json",
                      cookies={COOKIE_NAME: osess.mint_session(
                          "owner", secret=SESSION_SECRET, ttl_seconds=3600)}).status_code == 200


def test_release_verifier_still_reads_admin_json(client, monkeypatch):
    """The verifier role must keep working: it exists so automated verification can read protected
    surfaces without holding a credential that can act."""
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    _set_env(monkeypatch, "production")
    tok = mint_verifier_token(subject="auth-foundation",
                              secret=os.environ["RELEASE_VERIFIER_SIGNING_SECRET"])
    assert client.get("/admin/registry.json", headers={VERIFIER_HEADER: tok}).status_code == 200


def test_a_verifier_cannot_substitute_for_a_missing_key(client, no_key, monkeypatch):
    """A misconfigured process must not become readable just because a verifier token exists. When
    the config is invalid, nothing protected is served — to anyone."""
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    _set_env(no_key, "production")
    tok = mint_verifier_token(subject="auth-foundation",
                              secret=os.environ["RELEASE_VERIFIER_SIGNING_SECRET"])
    assert client.get("/admin/registry.json", headers={VERIFIER_HEADER: tok}).status_code == 401


# ── 4. the config decision itself ─────────────────────────────────────────────────────────────────
def test_auth_config_state_is_a_single_named_decision():
    """One decision, reached by every gate, so they cannot drift apart.

    The gates call `_auth_config_allows_open_access()`, which is the fail-closed wrapper around
    `auth_config_state()`. This asserts the whole chain rather than a single spelling, so it stays
    honest if the wrapper is renamed but keeps failing if a gate stops consulting the decision.
    """
    import inspect
    assert callable(getattr(core_api, "auth_config_state", None)), \
        "core.api.auth_config_state() does not exist — the decision is not centralised"

    # the wrapper must actually consult the decision, and must fail closed
    wrapper = inspect.getsource(core_api._auth_config_allows_open_access)
    assert "auth_config_state()" in wrapper
    assert "return False" in wrapper, "the wrapper does not fail closed on error"

    # every gate must reach it
    for fn in (core_api.verify_api_key, core_api.require_admin_json, core_api.api_key_middleware):
        src = inspect.getsource(fn)
        assert "_auth_config_allows_open_access()" in src, \
            f"{fn.__name__} does not consult the single auth-config decision"


def test_no_gate_still_returns_early_on_a_missing_key():
    """MUTATION GUARD on the exact defect. The old shape was a bare `if not _API_KEY: return`.
    Every gate must now branch on the config decision before it can return."""
    import ast, inspect, textwrap

    def _is_not_api_key(test) -> bool:
        """Exactly `not _API_KEY` — not merely any expression mentioning it. The
        `hmac.compare_digest(key, _API_KEY)` comparison is a different branch and must not be
        caught here; a guard that flags the wrong line gets deleted rather than obeyed."""
        return (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name) and test.operand.id == "_API_KEY")

    checked = 0
    for fn in (core_api.verify_api_key, core_api.require_admin_json):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.If) and _is_not_api_key(node.test)):
                continue
            checked += 1
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            assert "_auth_config_allows_open_access" in body, (
                f"{fn.__name__} returns on a missing API_KEY without consulting the config decision")
            assert "Raise" in body, f"{fn.__name__} does not refuse when the config is unusable"
    assert checked == 2, f"expected the `not _API_KEY` branch in both gates, found {checked}"


@pytest.mark.parametrize("app_env,key,expected", [
    ("production", "k", "OK"), ("staging", "k", "OK"), ("development", "k", "OK"),
    ("production", "", "MISCONFIGURED"), ("staging", "", "MISCONFIGURED"),
    ("prod", "", "MISCONFIGURED"), ("PRODUCTION", "", "MISCONFIGURED"),
    ("development", "", "DEV_OPEN"), ("local", "", "DEV_OPEN"), ("test", "", "DEV_OPEN"),
    ("", "", "MISCONFIGURED"), ("qa", "", "MISCONFIGURED"), ("banana", "", "MISCONFIGURED"),
])
def test_auth_config_state_truth_table(monkeypatch, app_env, key, expected):
    monkeypatch.setattr(core_api, "_API_KEY", key, raising=False)
    monkeypatch.setattr(core_api, "_APP_ENV", app_env, raising=False)
    state, _reason = core_api.auth_config_state()
    assert state == expected, f"APP_ENV={app_env!r} key={'set' if key else 'unset'} -> {state}"


def test_the_config_read_cannot_pass_vacuously(monkeypatch, client):
    """If deciding the config state ever raises, the request must be REFUSED, not allowed. A guard
    that opens when its own check breaks is not a guard."""
    def _boom():
        raise RuntimeError("config unreadable")
    monkeypatch.setattr(core_api, "auth_config_state", _boom)
    assert client.get("/admin/registry.json").status_code == 401
    assert client.get("/api/bots").status_code == 401


# ── 5. readiness makes it visible without leaking ─────────────────────────────────────────────────
def test_readiness_reports_the_misconfiguration(client, no_key):
    _set_env(no_key, "production")
    r = client.get("/api/health")
    assert r.status_code == 200, "health must stay reachable so the misconfiguration is observable"
    assert r.json().get("auth_config") == "MISCONFIGURED"


def test_readiness_reports_ok_when_configured(client, monkeypatch):
    _set_env(monkeypatch, "production")
    assert client.get("/api/health").json().get("auth_config") == "OK"


def test_readiness_never_returns_protected_content(client, no_key):
    """Surfacing a config problem must not become a second leak."""
    _set_env(no_key, "production")
    body = client.get("/api/health").text
    for marker in ("CapabilityRegistry", "security_tier", OWNER_KEY, "hourly_cycles"):
        assert marker not in body, f"/api/health leaked {marker!r}"
    assert len(client.get("/api/health").content) < 4096


# ── 6. no credential in a URL, in any configuration ───────────────────────────────────────────────
@pytest.mark.parametrize("app_env", HOSTED_ENVS + DEV_ENVS)
@pytest.mark.parametrize("session_enabled", [True, False])
def test_a_key_in_the_query_string_never_authenticates(client, monkeypatch, app_env, session_enabled):
    """The second HIGH defect. `resolve_api_key` honoured `?api_key=` whenever the unified session
    was disabled — which is the documented ROLLBACK state, so a rollback silently reinstated
    URL-borne credentials that land in edge logs, access logs, Referer headers and history.

    Correct credentials in a URL must be refused in EVERY configuration, so that rolling back a
    feature flag can never restore them."""
    import dataclasses
    _set_env(monkeypatch, app_env)
    monkeypatch.setattr(core_api, "_OPERATOR_SESSION_CFG",
                        dataclasses.replace(core_api._OPERATOR_SESSION_CFG,
                                            enabled=session_enabled))
    c = TestClient(core_api.app)
    for path in ("/admin/registry.json", "/api/bots"):
        r = c.get(f"{path}?api_key={OWNER_KEY}")
        assert r.status_code == 401, (
            f"{path}?api_key=… authenticated with APP_ENV={app_env} "
            f"session_enabled={session_enabled} — a URL credential still works")


def test_resolve_api_key_never_reads_the_query_string():
    """Pinned at the source so the branch cannot come back.

    Checks EXECUTABLE code only. The removed branch is quoted verbatim in the docstring, on purpose —
    this project supersedes wrong code visibly rather than erasing it, and a guard that greps raw
    source would force that record to be deleted to stay green."""
    import ast, inspect, textwrap
    from core import operator_session_web as osw

    tree = ast.parse(textwrap.dedent(inspect.getsource(osw.resolve_api_key)))
    fn = tree.body[0]
    # drop the docstring node, then render only the remaining executable statements
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)) else fn.body
    code = ast.dump(ast.Module(body=body, type_ignores=[]))
    assert "query_params" not in code, "resolve_api_key still reads a credential from the URL"
    assert "api_key" not in code.replace("'x-api-key'", ""), \
        "resolve_api_key references an api_key source other than the header"
    # and the record must survive
    assert "query_params" in inspect.getsource(osw.resolve_api_key), \
        "the removed branch is no longer documented at the site it was removed from"


def test_the_header_path_still_works(client, monkeypatch):
    _set_env(monkeypatch, "production")
    assert client.get("/admin/registry.json",
                      headers={"X-API-Key": OWNER_KEY}).status_code == 200
