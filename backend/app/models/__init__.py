# Path X: User model removed. Identity lives in public.profiles (FK to
# auth.users); see app.dependencies.supabase_jwt.UserPrincipal for the
# in-process JWT-derived representation, and app.models.profile.Profile
# for the SQLAlchemy mapper over the profiles table.
from app.models.admin import AdminUser, AuditLog
from app.models.alert import Alert, Watchlist
from app.models.api_key import ApiKey
from app.models.asset import Asset, PriceHistory
from app.models.cancellation_reason import CancellationReason
from app.models.conversation import Conversation, Message
from app.models.doc_chunk import KaiDocChunk
from app.models.document import KaiDocument
from app.models.memory import Memory
from app.models.prediction import Prediction
from app.models.profile import Profile
from app.models.stripe_event import ProcessedStripeEvent
from app.models.subscription import Subscription  # Plan removed: see app/services/billing/tiers.py
from app.models.usage import UsageLog
from app.models.sol import (
    SolConsent,
    SolCycle,
    SolGroup,
    SolMembership,
    SolPayment,
    SolPaymentProfile,
    SolPaymentProof,
    SolStripeAccount,
)

__all__ = [
    "AdminUser",
    "ApiKey",
    "AuditLog",
    "Alert",
    "Asset",
    "CancellationReason",
    "Conversation",
    "KaiDocChunk",
    "KaiDocument",
    "Memory",
    "Message",
    "Prediction",
    "PriceHistory",
    "ProcessedStripeEvent",
    "Profile",
    "SolConsent",
    "SolCycle",
    "SolGroup",
    "SolMembership",
    "SolPayment",
    "SolPaymentProfile",
    "SolPaymentProof",
    "SolStripeAccount",
    "Subscription",
    "UsageLog",
    "Watchlist",
]
