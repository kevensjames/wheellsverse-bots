"""Device identity and enrollment checks (Phase 7).

The theme: enrollment proves WHICH machine is talking and nothing more. Most of these
tests exist to prove a device cannot accumulate authority it was never granted.

    cd backend && python3 app/services/holding/test_device_identity.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

# holding -> services -> app -> backend (the import root)
_HERE = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

from app.services.holding import device_identity as di  # noqa: E402
from app.services.holding.device_identity import (  # noqa: E402
    BASELINE_SCOPES, ELEVATED_SCOPES, AuthenticationError, DeviceStatus, EnrollmentError,
    authenticate, begin_enrollment, complete_enrollment, confirm_enrollment, grant_scopes,
    revoke_device, rotate_key)

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(f"  {'ok ' if cond else 'FAIL'} {name}" + (f"  ({detail})" if detail and not cond else ""))


def expect_raises(name, exc_type, fn, needle=""):
    try:
        fn()
        check(name, False, "no exception raised")
    except exc_type as exc:
        check(name, needle.lower() in str(exc).lower() if needle else True, f"{exc}")
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"wrong exception {type(exc).__name__}: {exc}")


class MemStore:
    def __init__(self):
        self.devices, self.pairings, self.nonces = {}, {}, {}

    def get_device(self, device_id): return self.devices.get(device_id)
    def put_device(self, r): self.devices[r.device_id] = r
    def list_devices(self): return list(self.devices.values())
    def get_pairing(self, h): return self.pairings.get(h)
    def put_pairing(self, r): self.pairings[r.code_hash] = r
    def seen_nonce(self, d, n): return (d, n) in self.nonces

    def burn_nonce(self, d, n, exp):
        if (d, n) in self.nonces:
            return False
        self.nonces[(d, n)] = exp
        return True


def new_key():
    k = Ed25519PrivateKey.generate()
    pub = k.public_key().public_bytes(serialization.Encoding.Raw,
                                      serialization.PublicFormat.Raw)
    return k, pub


def enrolled(store, confirm=True):
    key, pub = new_key()
    code = begin_enrollment(store, owner_id="owner", device_name="Mac mini M4")
    dev = complete_enrollment(store, pairing_code=code, public_key=pub,
                              signature=key.sign(code.encode()), os_name="darwin", arch="arm64")
    if confirm:
        confirm_enrollment(store, device_id=dev.device_id,
                           fingerprint_shown=dev.fingerprint, owner_id="owner")
    return key, store.get_device(dev.device_id)


print("=== enrollment grants identity, not authority ===")
s = MemStore()
_k, dev = enrolled(s, confirm=False)
check("device starts PENDING_CONFIRMATION", dev.status == DeviceStatus.PENDING_CONFIRMATION)
check("device starts with ZERO scopes", dev.granted_scopes == set(), dev.granted_scopes)

_k, dev = enrolled(s)
check("confirmation grants baseline scopes only", dev.granted_scopes == set(BASELINE_SCOPES))
check("no elevated scope is granted at enrollment",
      not (dev.granted_scopes & ELEVATED_SCOPES), dev.granted_scopes & ELEVATED_SCOPES)
for scope in sorted(ELEVATED_SCOPES):
    check(f"  {scope} requires separate activation", scope not in dev.granted_scopes)

print("\n=== a device is never an owner ===")
key, dev = enrolled(MemStore() if False else s)
p = authenticate(s, device_id=dev.device_id, nonce="n" * 32,
                 signature=key.sign(("n" * 32).encode()))
check("principal role is 'device'", p.role == "device", p.role)
check("principal type is KAI_DEVICE", p.principal_type == "KAI_DEVICE")
check("principal carries no owner scope", "owner" not in str(p.scopes).lower())
check("principal cannot do an unactivated elevated action",
      not p.can("computer.desktop.interact"))
check("principal can do a baseline action", p.can("computer.mission.receive"))

print("\n=== pairing codes ===")
s2 = MemStore()
key2, pub2 = new_key()
code = begin_enrollment(s2, owner_id="owner", device_name="Laptop")
complete_enrollment(s2, pairing_code=code, public_key=pub2, signature=key2.sign(code.encode()))
expect_raises("pairing code is single-use", EnrollmentError,
              lambda: complete_enrollment(s2, pairing_code=code, public_key=pub2,
                                          signature=key2.sign(code.encode())), "already used")
s3 = MemStore()
code3 = begin_enrollment(s3, owner_id="owner", device_name="Old")
p3 = s3.get_pairing(__import__("hashlib").sha256(code3.encode()).hexdigest())
p3.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
k3, pk3 = new_key()
expect_raises("expired pairing code refused", EnrollmentError,
              lambda: complete_enrollment(s3, pairing_code=code3, public_key=pk3,
                                          signature=k3.sign(code3.encode())), "expired")
s4 = MemStore()
code4 = begin_enrollment(s4, owner_id="owner", device_name="X")
k4, pk4 = new_key()
wrong, _ = new_key()
expect_raises("enrollment without the private key refused", EnrollmentError,
              lambda: complete_enrollment(s4, pairing_code=code4, public_key=pk4,
                                          signature=wrong.sign(code4.encode())),
              "proof of possession")

print("\n=== operator fingerprint confirmation ===")
s5 = MemStore()
k5, d5 = enrolled(s5, confirm=False)
expect_raises("wrong fingerprint refused", EnrollmentError,
              lambda: confirm_enrollment(s5, device_id=d5.device_id,
                                         fingerprint_shown="AAAAAAAA-BBBBBBBB-CCCCCCCC-DDDDDDDD",
                                         owner_id="owner"), "fingerprint mismatch")
check("fingerprint is human-comparable (grouped)", d5.fingerprint.count("-") == 3, d5.fingerprint)

print("\n=== authentication, replay and revocation ===")
s6 = MemStore()
k6, d6 = enrolled(s6)
n = "a" * 32
authenticate(s6, device_id=d6.device_id, nonce=n, signature=k6.sign(n.encode()))
expect_raises("nonce replay refused", AuthenticationError,
              lambda: authenticate(s6, device_id=d6.device_id, nonce=n,
                                   signature=k6.sign(n.encode())), "replay")
expect_raises("forged signature refused", AuthenticationError,
              lambda: authenticate(s6, device_id=d6.device_id, nonce="b" * 32,
                                   signature=new_key()[0].sign(("b" * 32).encode())),
              "signature verification failed")
revoke_device(s6, device_id=d6.device_id, reason="lost laptop")
expect_raises("revoked device cannot authenticate", AuthenticationError,
              lambda: authenticate(s6, device_id=d6.device_id, nonce="c" * 32,
                                   signature=k6.sign(("c" * 32).encode())), "revoked")
check("revocation also clears scopes (defence in depth)",
      s6.get_device(d6.device_id).granted_scopes == set())
expect_raises("revoked device cannot be re-granted scopes", EnrollmentError,
              lambda: grant_scopes(s6, device_id=d6.device_id,
                                   scopes={"computer.desktop.observe"}, owner_id="owner"))

print("\n=== leases expire ===")
s7 = MemStore()
k7, d7 = enrolled(s7)
p7 = authenticate(s7, device_id=d7.device_id, nonce="d" * 32,
                  signature=k7.sign(("d" * 32).encode()), lease_ttl=timedelta(seconds=-1))
check("expired lease denies every scope", not p7.can("computer.mission.receive"))
check("expired lease is reported as expired", p7.lease_expired)

print("\n=== scope activation and rotation ===")
s8 = MemStore()
k8, d8 = enrolled(s8)
grant_scopes(s8, device_id=d8.device_id, scopes={"computer.desktop.observe"}, owner_id="owner")
d8 = s8.get_device(d8.device_id)
check("activated scope is granted", "computer.desktop.observe" in d8.granted_scopes)
check("activating one elevated scope does not grant the others",
      "computer.desktop.interact" not in d8.granted_scopes)
expect_raises("unknown scope refused", EnrollmentError,
              lambda: grant_scopes(s8, device_id=d8.device_id, scopes={"computer.everything"},
                                   owner_id="owner"), "unknown scopes")
k9, pk9 = new_key()
chal = "rotate-" + "e" * 24
before = set(s8.get_device(d8.device_id).granted_scopes)
rotate_key(s8, device_id=d8.device_id, new_public_key=pk9,
           signature=k9.sign(chal.encode()), challenge=chal)
d8 = s8.get_device(d8.device_id)
check("rotation preserves granted scopes", set(d8.granted_scopes) == before)
check("rotation records a new credential age", d8.key_rotated_at is not None)
n9 = "f" * 32
authenticate(s8, device_id=d8.device_id, nonce=n9, signature=k9.sign(n9.encode()))
check("new key authenticates after rotation", True)
expect_raises("old key no longer authenticates", AuthenticationError,
              lambda: authenticate(s8, device_id=d8.device_id, nonce="g" * 32,
                                   signature=k8.sign(("g" * 32).encode())), "signature")

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
sys.exit(1 if FAILED else 0)
