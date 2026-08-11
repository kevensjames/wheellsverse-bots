"""GDPR self-serve export (Art. 20) + delete (Art. 17). Deleting the profile
cascades to every user-owned table; export returns the caller's own data."""
from sqlalchemy import text

from app.models.conversation import Conversation, Message


def _seed(db, user):
    conv = Conversation(user_id=user.id, title="Test chat")
    db.add(conv)
    db.flush()
    db.add(Message(conversation_id=conv.id, user_id=user.id, role="user", content="hello"))
    db.commit()


def test_export_returns_own_data(client, db_session, free_user, auth_headers):
    _seed(db_session, free_user)
    r = client.get("/auth/me/export", headers=auth_headers(free_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"]["email"] == free_user.email
    assert len(body["conversations"]) == 1 and body["conversations"][0]["title"] == "Test chat"
    assert len(body["messages"]) == 1 and body["messages"][0]["content"] == "hello"


def test_delete_me_cascades_all_user_data(client, db_session, free_user, auth_headers):
    _seed(db_session, free_user)
    uid = str(free_user.id)
    r = client.delete("/auth/me", headers=auth_headers(free_user))
    assert r.status_code == 204

    def count(tbl):
        col = "id" if tbl == "profiles" else "user_id"
        return db_session.execute(
            text(f"SELECT count(*) FROM {tbl} WHERE {col} = :id"), {"id": uid}
        ).scalar()

    assert count("profiles") == 0        # the account itself
    assert count("conversations") == 0   # cascaded
    assert count("messages") == 0        # cascaded


def test_export_requires_auth(client):
    assert client.get("/auth/me/export").status_code in (401, 403)


def test_delete_requires_auth(client):
    assert client.delete("/auth/me").status_code in (401, 403)
