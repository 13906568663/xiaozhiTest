from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app, settings as app_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_create_tables", False)
    monkeypatch.setattr(app_settings, "auto_create_tables", False)
    monkeypatch.setattr(settings, "admin_username", "ops-admin")
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    monkeypatch.setattr(settings, "admin_display_name", "Ops Admin")

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def override_db_session() -> AsyncIterator:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def test_protected_route_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_auth_me_accepts_bearer_token(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "ops-admin", "password": "secret-pass"},
    )
    token = login_response.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "ops-admin"
    assert payload["display_name"] == "Ops Admin"
    assert payload["is_superuser"] is True
    assert any(role["code"] == "platform_admin" for role in payload["roles"])


def test_auth_me_accepts_cookie_token(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "ops-admin", "password": "secret-pass"},
    )
    token = login_response.json()["access_token"]
    cookie_name = get_settings().auth_cookie_name
    assert login_response.cookies.get(cookie_name) == token

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "ops-admin"
    assert payload["display_name"] == "Ops Admin"
    assert payload["is_superuser"] is True


def test_logout_clears_auth_cookie(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "ops-admin", "password": "secret-pass"},
    )

    cookie_name = get_settings().auth_cookie_name
    assert login_response.cookies.get(cookie_name)
    assert client.cookies.get(cookie_name)

    logout_response = client.post("/api/v1/auth/logout")

    assert logout_response.status_code == 200
    assert client.cookies.get(cookie_name) is None

    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 401
    assert me_response.json()["detail"] == "Authentication required."


def test_auth_me_accepts_generated_api_key(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "ops-admin", "password": "secret-pass"},
    )
    token = login_response.json()["access_token"]

    create_response = client.post(
        "/api/v1/profile/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "CLI Key"},
    )

    assert create_response.status_code == 200
    api_key_payload = create_response.json()
    plain_text_key = api_key_payload["plain_text_key"]

    bearer_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {plain_text_key}"},
    )
    assert bearer_response.status_code == 200
    assert bearer_response.json()["username"] == "ops-admin"

    profile_response = client.get(
        "/api/v1/profile",
        headers={"X-API-Key": plain_text_key},
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["user"]["username"] == "ops-admin"
    assert any(
        item["name"] == "CLI Key" for item in profile_response.json()["api_keys"]
    )


def test_deleted_api_key_is_rejected(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "ops-admin", "password": "secret-pass"},
    )
    token = login_response.json()["access_token"]

    create_response = client.post(
        "/api/v1/profile/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Temporary Key"},
    )
    assert create_response.status_code == 200

    created_api_key = create_response.json()
    delete_response = client.delete(
        f"/api/v1/profile/api-keys/{created_api_key['api_key']['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 204

    profile_response = client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile_response.status_code == 200
    assert all(
        item["id"] != created_api_key["api_key"]["id"]
        for item in profile_response.json()["api_keys"]
    )

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {created_api_key['plain_text_key']}"},
    )
    assert me_response.status_code == 401
    assert me_response.json()["detail"] == "Invalid API key."
