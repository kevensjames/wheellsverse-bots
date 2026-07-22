"""Command policy for the SWE sandbox — deny-by-default on dangerous patterns.

The sandbox already has --network none + no host mount, so egress/credential
commands are inert; rejecting them here makes intent auditable and blocks them
at the boundary rather than relying solely on isolation.
"""
from __future__ import annotations

from app.services.swe_runtime.config import SandboxPolicy, image_allowed


class PolicyDenied(Exception):
    """A command or image violated the sandbox policy."""


def validate(command: str, policy: SandboxPolicy) -> None:
    if not command or not command.strip():
        raise PolicyDenied("empty command")
    if not image_allowed(policy.image):
        raise PolicyDenied(f"image {policy.image!r} is not in KAI_SWE_IMAGE_ALLOWLIST")
    low = command.lower()
    for bad in policy.denied_substrings:
        if bad in low:
            raise PolicyDenied(f"command contains denied token {bad.strip()!r}")
