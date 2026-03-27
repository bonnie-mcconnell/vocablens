from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from starlette.requests import Request

from vocablens.api.dependencies_auth import get_user_repo
from vocablens.api.dependencies_core import get_admin_token
from vocablens.auth.jwt import decode_token
from vocablens.auth.jwt import ALGORITHM
from vocablens.auth.jwt import SECRET_KEY
from vocablens.core.time import utc_now
from vocablens.config.settings import settings
from vocablens.domain.errors import PersistenceError
from vocablens.main import create_app


class InMemoryUserRepo:
    def __init__(self):
        self._users_by_email = {}
        self._next_id = 1

    async def create(self, email: str, password_hash: str):
        if email in self._users_by_email:
            raise PersistenceError("duplicate")
        user = type(
            "UserRecord",
            (),
            {"id": self._next_id, "email": email, "password_hash": password_hash},
        )()
        self._users_by_email[email] = user
        self._next_id += 1
        return user

    async def get_by_email(self, email: str):
        return self._users_by_email.get(email)

    async def get_by_id(self, user_id: int):
        for user in self._users_by_email.values():
            if user.id == user_id:
                return user
        return None


def test_register_and_login_round_trip():
    app = create_app()
    repo = InMemoryUserRepo()
    app.dependency_overrides[get_user_repo] = lambda: repo
    client = TestClient(app)

    register = client.post(
        "/register",
        json={"email": "test@test.com", "password": "password123"},
    )
    assert register.status_code == 200
    register_payload = register.json()
    assert "access_token" in register_payload
    assert decode_token(register_payload["access_token"]) == 1

    login = client.post(
        "/login",
        json={"email": "test@test.com", "password": "password123"},
    )
    assert login.status_code == 200
    login_payload = login.json()
    assert "access_token" in login_payload
    assert decode_token(login_payload["access_token"]) == 1


def test_register_duplicate_email_returns_400():
    app = create_app()
    repo = InMemoryUserRepo()
    app.dependency_overrides[get_user_repo] = lambda: repo
    client = TestClient(app)

    first = client.post(
        "/register",
        json={"email": "test@test.com", "password": "password123"},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/register",
        json={"email": "test@test.com", "password": "different-pass"},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Email already registered"


def test_login_wrong_password_returns_401():
    app = create_app()
    repo = InMemoryUserRepo()
    app.dependency_overrides[get_user_repo] = lambda: repo
    client = TestClient(app)

    register = client.post(
        "/register",
        json={"email": "test@test.com", "password": "password123"},
    )
    assert register.status_code == 200

    login = client.post(
        "/login",
        json={"email": "test@test.com", "password": "wrong-password"},
    )
    assert login.status_code == 401
    assert login.json()["detail"] == "Invalid credentials"


def test_login_unknown_email_returns_401():
    app = create_app()
    repo = InMemoryUserRepo()
    app.dependency_overrides[get_user_repo] = lambda: repo
    client = TestClient(app)

    login = client.post(
        "/login",
        json={"email": "missing@test.com", "password": "password123"},
    )
    assert login.status_code == 401
    assert login.json()["detail"] == "Invalid credentials"


def test_decode_token_invalid_payload_raises_value_error():
    with pytest.raises(ValueError):
        decode_token("not-a-jwt")


def test_decode_token_expired_raises_value_error():
    now = utc_now()
    token = jose_jwt.encode(
        {
            "sub": "1",
            "iat": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    with pytest.raises(ValueError):
        decode_token(token)


def _request_with_headers(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/admin/reports/conversions",
        "headers": raw_headers,
    }
    return Request(scope)


def test_get_admin_token_accepts_matching_header():
    original_admin_token = settings.ADMIN_TOKEN
    try:
        object.__setattr__(settings, "ADMIN_TOKEN", "secret")
        request = _request_with_headers({"X-Admin-Token": "secret"})
        assert get_admin_token(request) == "secret"
    finally:
        object.__setattr__(settings, "ADMIN_TOKEN", original_admin_token)


def test_get_admin_token_rejects_missing_or_wrong_header():
    original_admin_token = settings.ADMIN_TOKEN
    try:
        object.__setattr__(settings, "ADMIN_TOKEN", "secret")
        wrong_request = _request_with_headers({"X-Admin-Token": "wrong"})
        missing_request = _request_with_headers({})

        with pytest.raises(HTTPException) as wrong_exc:
            get_admin_token(wrong_request)
        assert wrong_exc.value.status_code == 403

        with pytest.raises(HTTPException) as missing_exc:
            get_admin_token(missing_request)
        assert missing_exc.value.status_code == 403
    finally:
        object.__setattr__(settings, "ADMIN_TOKEN", original_admin_token)


def test_get_admin_token_rejects_when_admin_token_not_configured():
    original_admin_token = settings.ADMIN_TOKEN
    try:
        object.__setattr__(settings, "ADMIN_TOKEN", "")
        request = _request_with_headers({"X-Admin-Token": "secret"})
        with pytest.raises(HTTPException) as exc:
            get_admin_token(request)
        assert exc.value.status_code == 403
    finally:
        object.__setattr__(settings, "ADMIN_TOKEN", original_admin_token)
