"""
NarAI Godmode — encrypted credential vault + browser automation.
Public API:
    from narai_godmode import godmode
    godmode("open amazon_kdp create_book")

Note: `godmode` is imported lazily so that server-only consumers (e.g. the
FastAPI OAuth routes) can `from narai_godmode.adapters.google import …`
without pulling in the playwright-based CLI chain.
"""
__all__ = ["godmode"]


def __getattr__(name):
    if name == "godmode":
        from .cli import godmode as _godmode
        return _godmode
    raise AttributeError(f"module 'narai_godmode' has no attribute {name!r}")
