"""A validation error must never echo the submitted body back to the caller.

WHY THIS EXISTS. FastAPI's default RequestValidationError handler serialises ``exc.errors()``, and
every entry carries an ``input`` key holding the value the caller submitted. On an authentication
route that means a malformed request echoes the credential straight back. That is not hypothetical:
a mistyped field name on ``POST /admin/session/login`` echoed a live staging owner key into an
assistant transcript, and the key had to be rotated.

The route handler was never the problem — it is careful, and documented as careful. The validation
error is raised BEFORE the handler runs, so the handler's care never applied. The fix is an app-wide
exception handler, and this file proves it holds against the exact shapes that leaked.

Run: python3 -m app.test_validation_redaction
"""
from __future__ import annotations

res: list = []


def ck(name: str, ok: bool) -> None:
    res.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


CANARY = "canary-not-a-real-key-0123456789"


# Module scope on purpose: FastAPI resolves the annotation via get_type_hints, which cannot see a
# class defined inside a function — a locally-defined model is silently treated as a QUERY parameter
# and the route never receives a body at all.
from pydantic import BaseModel                                             # noqa: E402


class _LoginBody(BaseModel):
    secret: str


def _build(with_handler: bool):
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/login")
    def _login(body: _LoginBody):
        return {"ok": body.secret == "right"}

    if with_handler:
        from app.main import _install_safe_validation_handler
        _install_safe_validation_handler(app)
    return app


def _app_with_handler():
    return _build(True)


def _app_without_handler():
    return _build(False)


def run() -> bool:
    from fastapi.testclient import TestClient

    guarded = TestClient(_app_with_handler())
    bare = TestClient(_app_without_handler())

    # The three shapes that actually leaked, including the one where the SECRET FIELD'S OWN VALUE
    # reflects because it is the wrong JSON type rather than a wrong field name.
    shapes = {
        "wrong field name": {"api_key": CANARY},
        "misspelled field": {"secrett": CANARY},
        "right field, wrong type": {"secret": [CANARY]},
    }

    for label, body in shapes.items():
        r = guarded.post("/login", json=body)
        text = r.text
        ck(f"{label}: still 422 (callers can still fix their request)", r.status_code == 422)
        ck(f"{label}: the submitted value is NOT echoed", CANARY not in text)
        ck(f"{label}: no 'input' key in the response", '"input"' not in text)
        detail = r.json().get("detail")
        ck(f"{label}: the FIELD and reason are still reported",
           isinstance(detail, list) and detail and "loc" in detail[0] and "msg" in detail[0])

    # The guard must be proven to do something: unguarded, these SAME requests leak.
    leaks = 0
    for body in shapes.values():
        if CANARY in bare.post("/login", json=body).text:
            leaks += 1
    ck("control: WITHOUT the handler all three shapes leak the value (the test is not vacuous)",
       leaks == len(shapes))

    # A form body that is not a dict at all reflects the whole raw body in the default handler.
    r = guarded.post("/login", content=f"api_key={CANARY}",
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    ck("raw non-dict body is not echoed either", CANARY not in r.text)

    # A VALID request must be untouched by the handler.
    ok = guarded.post("/login", json={"secret": "right"})
    ck("a valid request is unaffected", ok.status_code == 200 and ok.json() == {"ok": True})
    bad = guarded.post("/login", json={"secret": "wrong"})
    ck("a well-formed but wrong credential still reaches the handler (401/200 logic preserved)",
       bad.status_code == 200 and bad.json() == {"ok": False})

    # Both apps must install it, not just one — App B was reachable directly and leaked identically.
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    a = (root / "core" / "api.py").read_text()
    b = (root / "backend" / "app" / "main.py").read_text()
    ck("App A (core/api.py) installs the handler", "_install_safe_validation_handler(app)" in a)
    ck("App B (backend/app/main.py) installs the handler", "_install_safe_validation_handler(app)" in b)

    bad_n = [n for n, ok_ in res if not ok_]
    print(f"\nVALIDATION REDACTION TESTS: {len(res) - len(bad_n)}/{len(res)} — "
          f"{'PASS' if not bad_n else 'FAIL'}")
    return not bad_n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
