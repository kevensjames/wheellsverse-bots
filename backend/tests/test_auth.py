from datetime import timedelta

from app.core.security import create_access_token
from app.models.user import User


SIGNUP = "/auth/signup"
LOGIN = "/auth/login"
REFRESH = "/auth/refresh"
ME = "/auth/me"


def _payload(faker):
    return {
        "email": faker.unique.email().lower(),
        "password": "testpass123",
        "full_name": faker.name(),
    }


# --- signup ---

def test_signup_success(client, db_session, faker_fixture):
    body = _payload(faker_fixture)
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["access_token"] and data["refresh_token"]
    assert data["token_type"] == "bearer"
    user = db_session.query(User).filter(User.email == body["email"]).first()
    assert user is not None
    assert user.full_name == body["full_name"]


def test_signup_duplicate_email(client, faker_fixture):
    body = _payload(faker_fixture)
    assert client.post(SIGNUP, json=body).status_code == 201
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 409


def test_signup_weak_password(client, faker_fixture):
    body = _payload(faker_fixture)
    body["password"] = "short"
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 422


def test_signup_invalid_email(client):
    r = client.post(SIGNUP, json={"email": "notanemail", "password": "testpass123"})
    assert r.status_code == 422


# --- login ---

def test_login_success(client, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    r = client.post(LOGIN, json={"email": body["email"], "password": body["password"]})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_login_wrong_password(client, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    r = client.post(LOGIN, json={"email": body["email"], "password": "wrongpass1"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_login_nonexistent_email(client):
    r = client.post(LOGIN, json={"email": "nobody@example.com", "password": "testpass123"})
    # Exact same message as wrong_password — no enumeration.
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_login_inactive_user(client, db_session, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    user = db_session.query(User).filter(User.email == body["email"]).first()
    user.is_active = False
    db_session.commit()
    r = client.post(LOGIN, json={"email": body["email"], "password": body["password"]})
    assert r.status_code == 403


# --- /me ---

def test_me_authenticated(client, faker_fixture):
    body = _payload(faker_fixture)
    tokens = client.post(SIGNUP, json=body).json()
    r = client.get(ME, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == body["email"]
    assert me["is_active"] is True
    assert me["is_verified"] is False


def test_me_no_token(client):
    r = client.get(ME)
    assert r.status_code == 401


def test_me_invalid_token(client):
    r = client.get(ME, headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_me_expired_token(client, db_session, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    user = db_session.query(User).filter(User.email == body["email"]).first()
    expired = create_access_token(str(user.id), expires_delta=timedelta(seconds=-1))
    r = client.get(ME, headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


# --- refresh ---

def test_refresh_success(client, faker_fixture):
    body = _payload(faker_fixture)
    tokens = client.post(SIGNUP, json=body).json()
    r = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["access_token"]
    assert new_tokens["refresh_token"]
    # Newly issued access token authenticates /me.
    me = client.get(ME, headers={"Authorization": f"Bearer {new_tokens['access_token']}"})
    assert me.status_code == 200


def test_refresh_with_access_token(client, faker_fixture):
    body = _payload(faker_fixture)
    tokens = client.post(SIGNUP, json=body).json()
    # Passing an access_token to /refresh should be rejected (wrong type claim).
    r = client.post(REFRESH, json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401


def test_refresh_invalid(client):
    r = client.post(REFRESH, json={"refresh_token": "garbage"})
    assert r.status_code == 401
