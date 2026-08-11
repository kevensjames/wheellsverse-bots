"""A refund or chargeback must revoke paid tier — a user can't keep a paid plan
after clawing the money back."""
from app.models.profile import Profile
from app.routers.billing import _handle_refund_or_dispute


def test_refund_downgrades_to_free(db_session, pro_user):
    _handle_refund_or_dispute(
        db_session, {"metadata": {"user_id": str(pro_user.id)}}, "charge.refunded"
    )
    assert db_session.get(Profile, pro_user.id).tier == "free"


def test_dispute_downgrades_to_free(db_session, pro_user):
    _handle_refund_or_dispute(
        db_session, {"metadata": {"user_id": str(pro_user.id)}}, "charge.dispute.created"
    )
    assert db_session.get(Profile, pro_user.id).tier == "free"


def test_unresolvable_refund_is_noop_not_crash(db_session):
    # dispute payload with no resolvable profile → logged, not raised
    _handle_refund_or_dispute(
        db_session, {"customer": "cus_does_not_exist"}, "charge.dispute.created"
    )
