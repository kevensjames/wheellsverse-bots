"""End-to-end smoke test for /auth. Requires uvicorn running on localhost:8000.

Run from backend/:  python -m scripts.smoke_test_auth
"""
import secrets
import sys

import httpx


BASE = "http://localhost:8000"
TOTAL = 4


def step(num: int, label: str, ok: bool, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    print(f"[{num}/{TOTAL}] {label:.<14} {tag}  {detail}")
    return ok


def main() -> int:
    email = f"smoke+{secrets.token_hex(4)}@wheellsverse.test"
    password = "smoketest123"
    results: list[bool] = []

    try:
        with httpx.Client(base_url=BASE, timeout=10) as c:
            # 1. Signup
            r = c.post("/auth/signup", json={"email": email, "password": password})
            results.append(step(1, "Signup", r.status_code == 201, f"HTTP {r.status_code}"))
            if not results[-1]:
                return 1

            # 2. Login (use fresh credentials — don't reuse signup tokens)
            r = c.post("/auth/login", json={"email": email, "password": password})
            results.append(step(2, "Login", r.status_code == 200, f"HTTP {r.status_code}"))
            if not results[-1]:
                return 1
            tokens = r.json()

            # 3. /me
            r = c.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
            ok = r.status_code == 200 and r.json().get("email") == email
            results.append(step(3, "Get /me", ok, f"HTTP {r.status_code}"))

            # 4. Refresh
            r = c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
            ok = r.status_code == 200 and "access_token" in r.json()
            results.append(step(4, "Refresh", ok, f"HTTP {r.status_code}"))
    except httpx.ConnectError:
        print("FAIL — cannot reach http://localhost:8000. Is uvicorn running?")
        return 2

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
