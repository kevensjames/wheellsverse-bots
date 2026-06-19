"""Phase B Step 1 — dual post-schema read reconciliation.

nx_posts has two parallel column pairs:
  legacy  create_post   -> writes `body` + `access` (access default 'subscribers')
  entity  Post.create   -> writes `text` + `access_type` (access_type default 'free')

Public readers gated on p["access"]=="free" and rendered p["body"], so entity-created
posts were invisible (access left at default 'subscribers') and blank (body left at '').
list_posts now normalizes both, using the populated CONTENT column as the discriminator
(entity rows have text, legacy rows have body) so the right gating column wins.
"""
import pytest
from core import nexora_db, nexora_auth, nexora_entities as ent
from core import nexora_payments as pay
import core.api as api
from fastapi.testclient import TestClient


def _sub_checkout(stripe_id, creator_email, fan_email):
    return {"type": "checkout.session.completed",
            "data": {"object": {"id": stripe_id, "amount_total": 1000, "payment_intent": stripe_id,
                                "metadata": {"type": "subscription", "fan_email": fan_email,
                                             "creator_email": creator_email}}}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db


def _creator(email="c@x.com"):
    nexora_auth.register_creator(email, "hunter2", "C")
    ent.entity_create("CreatorProfile", {"display_name": "C"}, {"email": email, "role": "creator"})
    conn = nexora_db.get_conn()
    row = conn.execute("SELECT id, handle FROM nx_creators WHERE email=?", (email,)).fetchone()
    conn.close()
    return row["id"], row["handle"]


def _entity_post(email, text, access_type):
    return ent.entity_create("Post", {"title": "T", "text": text, "access_type": access_type},
                             {"email": email, "role": "creator"})


def test_entity_free_post_is_publicly_visible(db):
    cid, _ = _creator()
    _entity_post("c@x.com", "hello world", "free")
    posts = nexora_db.list_posts(cid)
    assert len(posts) == 1
    assert posts[0]["access"] == "free"            # normalized from access_type (was 'subscribers' default)
    assert posts[0]["body"] == "hello world"       # normalized from text (was '' default)


def test_entity_subscribers_post_hidden_from_free_feed(db):
    cid, _ = _creator("s@x.com")
    _entity_post("s@x.com", "secret", "subscribers")
    posts = nexora_db.list_posts(cid)
    assert posts[0]["access"] != "free"            # stays gated


def test_legacy_subscribers_post_not_exposed_as_free(db):
    # The high-severity tie-breaker: legacy access='subscribers' must NOT be leaked as free
    # just because access_type defaults to 'free'.
    cid, _ = _creator("l@x.com")
    nexora_db.create_post(cid, "T", "legacy body", access="subscribers")
    posts = nexora_db.list_posts(cid)
    assert posts[0]["access"] == "subscribers"
    assert posts[0]["body"] == "legacy body"


def test_legacy_free_post_still_visible(db):
    cid, _ = _creator("lf@x.com")
    nexora_db.create_post(cid, "T", "legacy free body", access="free")
    posts = nexora_db.list_posts(cid)
    assert posts[0]["access"] == "free"
    assert posts[0]["body"] == "legacy free body"


def test_public_posts_locked_branch_blanks_text(db):
    # A gated entity post viewed by a non-subscriber must not leak content via the raw `text` column.
    cid, handle = _creator("lk@x.com")
    _entity_post("lk@x.com", "premium secret", "subscribers")
    c = TestClient(api.app)
    r = c.get(f"/api/nx/creator/{handle}/posts")   # no fan_email -> not subscribed
    assert r.status_code == 200
    posts = r.json()["posts"]
    assert len(posts) == 1 and posts[0].get("locked") is True
    assert posts[0]["body"] == ""
    assert posts[0].get("text", "") == ""          # content must not leak


def test_posts_paywall_requires_token_not_query_param(db):
    # IDOR regression: the paywall must authenticate via Bearer token, never trust
    # a fan_email query param (an attacker could pass a known subscriber's email).
    cid, handle = _creator("idor@x.com")
    _entity_post("idor@x.com", "premium secret", "subscribers")
    fan = nexora_auth.register_fan("fan@x.com", "hunter2")
    pay.handle_stripe_event(_sub_checkout("cs_sub", "idor@x.com", "fan@x.com"))   # fan is now subscribed
    c = TestClient(api.app)
    # Attacker spoofs the subscriber email with NO token -> must stay locked.
    r = c.get(f"/api/nx/creator/{handle}/posts?fan_email=fan@x.com")
    assert r.json()["is_subscribed"] is False
    assert r.json()["posts"][0].get("locked") is True
    assert r.json()["posts"][0]["body"] == ""
    # The real fan, authenticated by token -> unlocked.
    r2 = c.get(f"/api/nx/creator/{handle}/posts", headers={"Authorization": f"Bearer {fan['token']}"})
    assert r2.json()["is_subscribed"] is True
    assert r2.json()["posts"][0]["body"] == "premium secret"
