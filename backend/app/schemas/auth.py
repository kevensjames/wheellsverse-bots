from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Returned alongside cookies for API clients that don't carry a cookie jar."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    """Path X: maps to public.profiles. is_verified/is_active/phone were
    SQLAlchemy User fields and have no clean equivalent on profiles —
    dropped. Add them back if the UI grows a need."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None = None
    tier: str = "free"
    created_at: datetime | None = None
