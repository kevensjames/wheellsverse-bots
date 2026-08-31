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
