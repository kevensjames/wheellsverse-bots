"""Path X: thin re-export shim over ``supabase_jwt``.

Existing imports (``from app.dependencies.auth import get_current_user``) keep
working — they now get the Supabase-JWT-backed UserPrincipal instead of a
SQLAlchemy User row. No DB round-trip on every request anymore: the JWT
already carries id + email + role.

The Stage 6 cookie-or-Bearer hybrid is preserved (header wins on collision).
"""
from app.dependencies.supabase_jwt import (
    UserPrincipal,
    decode_supabase_jwt,
    get_current_user,
)


__all__ = ["UserPrincipal", "decode_supabase_jwt", "get_current_user"]
