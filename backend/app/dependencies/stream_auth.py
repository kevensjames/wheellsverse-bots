"""Path X: thin re-export shim for SSE auth.

The Stage 4 query-param token + Stage 6 cookie hybrid both moved into
``supabase_jwt.get_user_for_stream``. This module exists so
``routers/nai.py`` keeps importing from the path it always has.

``get_user_from_query_token`` alias is preserved for any callers we haven't
audited yet (grep shows only nai.py uses it).
"""
from app.dependencies.supabase_jwt import get_user_for_stream


get_user_from_query_token = get_user_for_stream

__all__ = ["get_user_for_stream", "get_user_from_query_token"]
