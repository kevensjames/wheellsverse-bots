"""App-Store Step 0 — consumer/operator profile split (KAI_PROFILE).

The consumer backend must mount ONLY the public /kai/* product surface; the
whole /admin/* control plane + Sol/Dwolla money ops must be physically
unregistered (404), not just auth-gated. Run in a subprocess so each profile
gets a fresh module import without polluting the shared app/settings singletons.
"""
import os
import subprocess
import sys

_BACKEND = os.path.dirname(os.path.dirname(__file__))


def _routes_for(profile: str) -> list[str]:
    env = dict(os.environ)
    env["KAI_PROFILE"] = profile
    env.setdefault("DATABASE_URL", "postgresql://u:p@localhost/d")
    code = "import app.main as m; print('\\n'.join(getattr(r, 'path', '') for r in m.app.routes))"
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=_BACKEND,
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    return [ln for ln in out.stdout.splitlines() if ln]


def test_consumer_profile_hides_operator_surface():
    paths = _routes_for("consumer")
    assert [p for p in paths if p.startswith("/admin")] == [], "operator /admin/* leaked into consumer"
    assert [p for p in paths if p.startswith("/sol")] == [], "Sol money surface leaked into consumer"
    # but the public product surface is intact
    assert "/kai/chat" in paths
    assert any(p.startswith("/billing") for p in paths)
    assert any(p.startswith("/auth") for p in paths)


def test_operator_profile_mounts_full_control_plane():
    paths = _routes_for("operator")
    assert len([p for p in paths if p.startswith("/admin")]) > 50
    assert "/kai/chat" in paths  # chat available in both profiles
