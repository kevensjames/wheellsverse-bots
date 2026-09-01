"""KAI Capability Fabric — LIVE per-transport adapters (Wave B, §21/§22).

The first capabilities to move from DISCOVERED → genuinely installed+certified plug in here,
behind the same ``CapabilityAdapter`` ABC as ``ExternalBlockedAdapter``. Unlike the pure-stdlib
``adapter.py``, this module may import an external dependency — but ONLY lazily, inside methods,
so the fabric still imports and tests cleanly where the dependency is absent (``health`` then
reports OFFLINE honestly and ``invoke`` returns a Failure, never a fabricated success, §73/§74).

Every adapter result flows through ``results.normalize`` → UNTRUSTED, injection-scanned data
(§24). A converted document is data KAI reasons over, never instructions it obeys.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from .adapter import CapabilityAdapter, Transport
from .results import NormalizedResult, ResultKind, Provenance, normalize

# formats MarkItDown converts (the sub-capabilities the LIBRARY transport actually exposes)
_MARKITDOWN_FORMATS = [
    "pdf", "docx", "pptx", "xlsx", "xls", "html", "csv", "json", "xml",
    "txt", "md", "epub", "zip", "image", "audio", "youtube_url",
]


class MarkItDownAdapter(CapabilityAdapter):
    """microsoft/markitdown behind the LIBRARY transport — in-process document → Markdown.

    Certified LOCAL: proven on real files in-process where markitdown is installed. Where it is
    NOT installed (e.g. the deployed App B runtime until it is added there), ``health`` reports
    OFFLINE and ``invoke`` returns a Failure — the honest EXTERNAL_BLOCKED behavior, never faked.
    """

    def __init__(self) -> None:
        super().__init__("markitdown", Transport.LIBRARY)
        self._md = None

    def _new_engine(self):
        from markitdown import MarkItDown  # lazy import — may raise ImportError where absent
        return MarkItDown()

    def _importable(self) -> tuple[bool, str]:
        try:
            import markitdown  # noqa: F401
            ver = getattr(markitdown, "__version__", "unknown")
            return True, f"markitdown {ver}"
        except Exception as e:  # ImportError or a broken partial install
            return False, f"{e.__class__.__name__}: {e}"

    def discover(self) -> list[str]:
        ok, _ = self._importable()
        return ["convert", *(_MARKITDOWN_FORMATS if ok else [])]

    def health(self) -> dict:
        ok, detail = self._importable()
        return {"state": "READY" if ok else "OFFLINE",
                "reason": detail if ok else f"EXTERNAL_BLOCKED: {detail}"}

    def start(self) -> None:
        self._md = self._new_engine()   # raises where markitdown is absent (honest)

    def stop(self) -> None:
        self._md = None

    def invoke(self, request: dict) -> NormalizedResult:
        """request = {"path": "<file>"}  (a converted document is UNTRUSTED data, §24)."""
        path = (request or {}).get("path")
        if not path:
            return normalize(self.id, ResultKind.FAILURE, summary="markitdown: no 'path' in request",
                             provenance=Provenance.UNAVAILABLE, data={"request": request})
        ok, detail = self._importable()
        if not ok:
            return normalize(self.id, ResultKind.FAILURE,
                             summary=f"markitdown EXTERNAL_BLOCKED: {detail}",
                             provenance=Provenance.UNAVAILABLE, data={"request": request})
        try:
            engine = self._md or self._new_engine()
            result = engine.convert(path)
            text = getattr(result, "text_content", "") or ""
        except Exception as e:
            return normalize(self.id, ResultKind.FAILURE,
                             summary=f"markitdown conversion failed: {e.__class__.__name__}: {e}",
                             provenance=Provenance.UNAVAILABLE, data={"path": path})
        # ARTIFACT: a produced document. normalize() scans it for injection + pins trust UNTRUSTED.
        return normalize(
            self.id, ResultKind.ARTIFACT,
            summary=f"converted {path.split('/')[-1]} -> markdown ({len(text)} chars)",
            data={"markdown": text, "chars": len(text), "source_path": path},
            provenance=Provenance.REAL,
        )

    def cancel(self, invocation_id: str) -> None:
        return None


class YtDlpAdapter(CapabilityAdapter):
    """yt-dlp behind the LIBRARY transport — authorized media metadata + gated download (§27/§80).

    The CERTIFIED path is READ-ONLY metadata extraction (``extract_info(download=False)``): it
    returns an Observation of a small, injection-scanned metadata subset. An actual DOWNLOAD is
    never performed here — ``invoke({"action":"download"})`` returns an inert ActionProposal that
    only governance (§22) + an authorized-content decision (§80) can turn executable. Where yt-dlp
    is absent, ``health`` is OFFLINE and ``invoke`` returns a Failure — never a fabricated result.
    """

    def __init__(self) -> None:
        super().__init__("yt-dlp", Transport.LIBRARY)

    def _importable(self) -> tuple[bool, str]:
        try:
            import yt_dlp  # noqa: F401
            return True, f"yt-dlp {getattr(yt_dlp.version, '__version__', 'unknown')}"
        except Exception as e:
            return False, f"{e.__class__.__name__}: {e}"

    def discover(self) -> list[str]:
        return ["extract_info", "download"]

    def health(self) -> dict:
        ok, detail = self._importable()
        return {"state": "READY" if ok else "OFFLINE",
                "reason": detail if ok else f"EXTERNAL_BLOCKED: {detail}"}

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def invoke(self, request: dict) -> NormalizedResult:
        request = request or {}
        url = request.get("url")
        action = request.get("action", "extract_info")
        if not url:
            return normalize(self.id, ResultKind.FAILURE, summary="yt-dlp: no 'url' in request",
                             provenance=Provenance.UNAVAILABLE, data={"request": request})
        # A DOWNLOAD is never executed here — it is proposed, inert, and requires authorization (§80).
        if action == "download":
            return normalize(
                self.id, ResultKind.ACTION_PROPOSAL,
                summary=f"proposed download of {url} — requires authorized-content approval (§80)",
                provenance=Provenance.REAL,
                proposed_action={"capability": "yt-dlp", "action": "download", "url": url,
                                 "gate": "authorized-content + governance approval"},
                data={"url": url},
            )
        if action != "extract_info":
            return normalize(self.id, ResultKind.FAILURE, summary=f"yt-dlp: unknown action {action!r}",
                             provenance=Provenance.UNAVAILABLE, data={"request": request})
        ok, detail = self._importable()
        if not ok:
            return normalize(self.id, ResultKind.FAILURE, summary=f"yt-dlp EXTERNAL_BLOCKED: {detail}",
                             provenance=Provenance.UNAVAILABLE, data={"request": request})
        try:
            import yt_dlp
            opts = {"quiet": True, "skip_download": True, "noplaylist": True, "socket_timeout": 25}
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=False) or {}
        except Exception as e:
            return normalize(self.id, ResultKind.FAILURE,
                             summary=f"yt-dlp metadata extraction failed: {e.__class__.__name__}",
                             provenance=Provenance.UNAVAILABLE, data={"url": url})
        # a SMALL metadata subset only (the full info dict is huge + attacker-influenced text)
        meta = {k: info.get(k) for k in ("id", "title", "uploader", "creator", "duration",
                                         "extractor", "webpage_url", "license")}
        meta["format_count"] = len(info.get("formats") or [])
        return normalize(
            self.id, ResultKind.OBSERVATION,
            summary=f"metadata: {str(meta.get('title'))[:60]} ({meta.get('duration')}s, {meta['format_count']} formats)",
            data=meta, provenance=Provenance.REAL,   # title/uploader are attacker-influenced -> scanned, UNTRUSTED
        )

    def cancel(self, invocation_id: str) -> None:
        return None


class CodebaseMemoryMcpAdapter(CapabilityAdapter):
    """DeusData/codebase-memory-mcp behind the SUBPROCESS transport — local code intelligence (§18).

    Built FROM SOURCE (not the prebuilt binary) + source-reviewed before first run. Invokes the tool's
    one-shot ``cli`` mode (never its ``install`` command, which reconfigures external clients). Only a
    READ-ONLY / analysis tool allowlist is permitted; destructive/config tools (delete_project, install,
    uninstall, update) are refused here. The binary path comes from ``$CBM_BIN`` (or PATH); where it is
    not configured, ``health`` is OFFLINE and ``invoke`` returns a Failure — never a fabricated result.
    Code content it returns is UNTRUSTED data (§24). No shell is used (argv list form → no shell injection).
    """

    _ALLOWED = frozenset({
        "index_repository", "search_code", "search_graph", "query_graph", "trace_path",
        "get_code_snippet", "get_graph_schema", "get_architecture", "list_projects",
        "index_status", "check_index_coverage", "detect_changes", "compare_graphs",
    })
    _REFUSED = frozenset({"delete_project", "install", "uninstall", "update"})

    def __init__(self) -> None:
        super().__init__("codebase-memory-mcp", Transport.SUBPROCESS)

    def _binary(self) -> str | None:
        b = os.environ.get("CBM_BIN") or shutil.which("codebase-memory-mcp")
        return b if (b and os.path.isfile(b) and os.access(b, os.X_OK)) else None

    def discover(self) -> list[str]:
        return sorted(self._ALLOWED) if self._binary() else []

    def health(self) -> dict:
        b = self._binary()
        return {"state": "READY", "reason": f"binary at {b}"} if b else \
               {"state": "OFFLINE", "reason": "EXTERNAL_BLOCKED: set $CBM_BIN to the built binary"}

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def invoke(self, request: dict) -> NormalizedResult:
        request = request or {}
        tool = request.get("tool")
        flags = request.get("flags") or {}
        if tool in self._REFUSED:
            return normalize(self.id, ResultKind.FAILURE,
                             summary=f"refused: '{tool}' is destructive/config-mutating, not permitted (§18)",
                             provenance=Provenance.UNAVAILABLE, data={"tool": tool})
        if tool not in self._ALLOWED:
            return normalize(self.id, ResultKind.FAILURE, summary=f"unknown/again-not-allowed tool {tool!r}",
                             provenance=Provenance.UNAVAILABLE, data={"tool": tool})
        b = self._binary()
        if not b:
            return normalize(self.id, ResultKind.FAILURE,
                             summary="codebase-memory-mcp EXTERNAL_BLOCKED: binary not configured ($CBM_BIN)",
                             provenance=Provenance.UNAVAILABLE, data={"request": request})
        # argv list form (NO shell): flags are --key=value with string values only
        argv = [b, "cli", "--json", tool]
        for k, v in flags.items():
            argv.append(f"--{str(k).replace('_', '-')}={v}")
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                                  env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        except Exception as e:
            return normalize(self.id, ResultKind.FAILURE,
                             summary=f"codebase-memory-mcp run failed: {e.__class__.__name__}",
                             provenance=Provenance.UNAVAILABLE, data={"tool": tool})
        # the tool prints log lines + a final JSON-RPC-ish result line; take the last JSON object
        payload = None
        for line in reversed((proc.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    payload = json.loads(line); break
                except ValueError:
                    continue
        if payload is None:
            return normalize(self.id, ResultKind.FAILURE, summary="no JSON result from codebase-memory-mcp",
                             provenance=Provenance.UNAVAILABLE, data={"stderr": (proc.stderr or "")[:300]})
        if payload.get("isError"):
            return normalize(self.id, ResultKind.FAILURE,
                             summary=f"codebase-memory-mcp tool error: {tool}",
                             provenance=Provenance.UNAVAILABLE, data=payload.get("structuredContent", payload))
        # code-intelligence output is UNTRUSTED data (a repo can contain injection text)
        return normalize(self.id, ResultKind.OBSERVATION, summary=f"codebase-memory-mcp {tool} ok",
                         data=payload.get("structuredContent", payload), provenance=Provenance.REAL)

    def cancel(self, invocation_id: str) -> None:
        return None
