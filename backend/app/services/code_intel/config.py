"""Per-tenant code-intelligence policy + module defaults.

Deny-by-default: with no allowlisted roots configured, nothing is indexable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Directories never indexed (VCS internals, deps, build output, caches).
DEFAULT_EXCLUDE_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "vendor", "bower_components",
    "dist", "build", "out", "target", ".next", ".nuxt", "__pycache__",
    ".venv", "venv", "env", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".gradle", ".idea", ".vscode", "coverage", ".terraform", "site-packages",
})

# File-name globs never indexed (secrets, binaries, lockfiles, media).
DEFAULT_EXCLUDE_FILE_GLOBS = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.pfx", "*.p12",
    "*.crt", "*.cer", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "*.lock", "*.min.js", "*.map", "*.png", "*.jpg", "*.jpeg", "*.gif",
    "*.pdf", "*.zip", "*.tar", "*.gz", "*.tgz", "*.zst", "*.7z",
    "*.so", "*.dylib", "*.dll", "*.o", "*.a", "*.class", "*.jar", "*.wasm",
    "*.bin", "*.exe", "*.ico", "*.woff", "*.woff2", "*.ttf", "*.eot",
    "*.mp4", "*.mov", "*.mp3", "credentials", "credentials.json",
    ".npmrc", ".pypirc", ".netrc", "*.keystore", "*.jks",
)

DEFAULT_MAX_FILE_BYTES = int(os.environ.get("KAI_CODE_INTEL_MAX_FILE_BYTES", "1000000"))  # 1 MB
DEFAULT_MAX_CHUNKS_PER_REPO = int(os.environ.get("KAI_CODE_INTEL_MAX_CHUNKS", "50000"))
DEFAULT_EMBED_BATCH = 96


@dataclass(slots=True)
class CodeIntelPolicy:
    """Per-tenant policy. ``allowlisted_roots`` are the ONLY absolute dirs a
    tenant may index under; an index request naming paths outside these is
    rejected by the walker."""
    allowlisted_roots: tuple[str, ...] = ()
    embedding_provider: str = "openai"       # "openai" | "ollama"
    egress_allowed: bool = True              # False => a local provider is forced
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_chunks_per_repo: int = DEFAULT_MAX_CHUNKS_PER_REPO
    exclude_dirs: frozenset = DEFAULT_EXCLUDE_DIRS
    exclude_file_globs: tuple = DEFAULT_EXCLUDE_FILE_GLOBS


def _split_env_list(name: str) -> tuple[str, ...]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return ()
    sep = os.pathsep if os.pathsep in raw else ","
    return tuple(p.strip() for p in raw.split(sep) if p.strip())


def resolve_policy(user_id) -> CodeIntelPolicy:
    """Resolve the tenant's policy. MVP reads env defaults; a future commit
    swaps this for a per-tenant DB lookup (mirrors composio_auth's Phase-B
    TODO). ``egress_allowed=False`` forces a local embedding provider so a
    residency-restricted tenant never reaches an external embedding API."""
    provider = (os.environ.get("KAI_CODE_INTEL_EMBEDDING_PROVIDER") or "openai").strip().lower()
    egress = (os.environ.get("KAI_CODE_INTEL_EGRESS", "1").strip().lower()
              in ("1", "true", "yes", "on"))
    if not egress and provider == "openai":
        provider = "ollama"
    return CodeIntelPolicy(
        allowlisted_roots=_split_env_list("KAI_CODE_INTEL_ROOTS"),
        embedding_provider=provider,
        egress_allowed=egress,
    )
