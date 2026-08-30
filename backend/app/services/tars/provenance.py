"""Upstream provenance for the UI-TARS / Agent TARS execution worker (KAI integration).

Pins the EXACT upstream artifact KAI is allowed to talk to. Never `latest` in a
certified configuration. Reviewed before any install/run; the worker adapter refuses
to certify a worker whose reported upstream_version != PINNED.upstream_version.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Provenance:
    repository: str
    release: str
    package: str
    package_version: str          # pinned — NEVER "latest"
    commit: str                   # exact tag commit (to be filled from the release tag at fetch time)
    license: str
    supported_node: str
    integration_surface: str
    retrieved_at: str
    integrity_hash: str           # sha256 of the pinned tarball; verified at install time
    review_status: str

    def as_dict(self) -> dict:
        return asdict(self)


# Reviewed 2026-08-30. Apache-2.0 confirmed. Latest stable Agent TARS CLI is v0.3.0
# (2025-11-05). The exact tag commit + tarball integrity hash are filled in and verified
# at the (separately gated) install step — NOT hardcoded to a guess.
PINNED = Provenance(
    repository="https://github.com/bytedance/UI-TARS-desktop",
    release="agent-tars-cli@0.3.0",
    package="@agent-tars/cli",
    package_version="0.3.0",              # pinned exact — never latest
    commit="",                            # filled + verified at install (release tag SHA)
    license="Apache-2.0",
    supported_node=">=22",
    integration_surface="agent-tars-headless-server",   # SDK/headless server, NOT the desktop GUI
    retrieved_at="2026-08-30",
    integrity_hash="",                    # sha256 of the pinned tarball; verified at install
    review_status="AUDITED_PENDING_INSTALL",  # provenance reviewed; install gated on operator approval
)


def is_pinned(version: str) -> bool:
    """A worker's reported upstream version is acceptable only if it EXACTLY matches the pin."""
    return bool(version) and version == PINNED.package_version


def _demo():
    assert PINNED.license == "Apache-2.0"
    assert PINNED.package_version and PINNED.package_version != "latest"
    assert is_pinned("0.3.0") is True
    assert is_pinned("latest") is False and is_pinned("0.2.9") is False and is_pinned("") is False
    print("provenance self-check: PASS")


if __name__ == "__main__":
    _demo()
