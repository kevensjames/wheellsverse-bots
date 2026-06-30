"""Admin auth: shared-secret header, constant-time comparison.

Hardening (audit AUTHZ-004):
  * constant-time compare (hmac.compare_digest) so a wrong token can't be
    recovered via response-timing differences;
  * fail-closed when no token is configured or supplied;
  * a loud one-time warning when the dedicated ADMIN_TOKEN is unset and the
    daemon is falling back to JWT_SECRET_KEY (deprecated — rotate to a
    dedicated token). The fallback is intentionally KEPT to avoid locking the
    operator out before .env is updated.

Stage 11 replaces this with real `admin_users` table auth + rotation/RBAC.
"""
import hmac
import logging

from fastapi import Header, HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

# Surface the weak-config case once at import rather than silently.
if not settings.ADMIN_TOKEN and settings.JWT_SECRET_KEY:
    logger.warning(
        "admin auth: ADMIN_TOKEN is unset — falling back to JWT_SECRET_KEY. "
        "Set a dedicated ADMIN_TOKEN and rotate it; the fallback is deprecated."
    )
elif not settings.admin_token:
    logger.warning("admin auth: no admin token configured — all /admin/* access is denied.")


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    expected = settings.admin_token
    # Fail closed: no configured token or no supplied token → reject. Use a
    # constant-time comparison to avoid a timing side-channel on the secret.
    if (
        not expected
        or not x_admin_token
        or not hmac.compare_digest(str(x_admin_token), str(expected))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin token required",
        )
