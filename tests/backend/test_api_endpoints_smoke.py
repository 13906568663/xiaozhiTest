from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import ChatMessage, ChatSession, NodeRun, NodeRunArtifact
from app.db.session import get_db_session
from app.main import app, settings as app_settings
from tests.backend.http_api_mock import MockHttpApiServer


@pytest.fixture
def api_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_create_tables", False)
    monkeypatch.setattr(app_settings, "auto_create_tables", False)
    monkeypatch.setattr(settings, "openai_api_key", None)
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

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    with TestClient(app) as test_client:
        yield {
            "client": test_client,
            "session_factory": session_factory,
        }
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _client(api_env: dict[str, object]) -> TestClient:
    return api_env["client"]  # type: ignore[return-value]


def _session_factory(api_env: dict[str, object]) -> async_sessionmaker[AsyncSession]:
    return api_env["session_factory"]  # type: ignore[return-value]


def _login_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "ops-admin", "password": "secret-pass"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_public_endpoints_and_auth_logout(api_env: dict[str, object]) -> None:
    client = _client(api_env)

    root_response = client.get("/")
    assert root_response.status_code == 200
    assert root_response.json()["docs"] == "/docs"

    health_response = client.get("/api/v1/healthz")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"

    headers = _login_headers(client)

    me_response = client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "ops-admin"

    logout_response = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_response.status_code == 200
    assert logout_response.json()["success"] is True



def test_knowledge_base_can_bind_provider_reference(
    api_env: dict[str, object],
) -> None:
    client = _client(api_env)
    headers = _login_headers(client)

    create_capability_response = client.post(
        "/api/v1/capabilities",
        headers=headers,
        json={
            "type": "model",
            "code": "kb_embedding_provider",
            "name": "KB Embedding Provider",
            "description": "Provider for knowledge base embeddings",
            "status": "active",
            "config_json": {
                "api_mode": "openai_compatible",
                "api_host": "https://provider.example/v1",
                "api_path": "/chat/completions",
                "api_key": "provider-test-key",
                "model_name": "gpt-5.2",
                "available_models": [
                    {
                        "id": "text-embedding-3-small",
                        "model_type": "embedding",
                    }
                ],
            },
        },
    )
    assert create_capability_response.status_code == 200

    create_kb_response = client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={
            "code": "product_docs",
            "name": "Product Docs",
            "description": "Knowledge base backed by provider binding",
            "status": "active",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 1536,
            "embedding_config": {
                "provider_ref": "kb_embedding_provider",
                "api_host": "https://should-not-be-saved.example/v1",
                "api_key": "should-not-be-saved",
                "api_path": "/embeddings",
            },
            "chunk_method": "fixed",
            "chunk_size": 512,
            "chunk_overlap": 64,
        },
    )
    assert create_kb_response.status_code == 200

    payload = create_kb_response.json()
    assert payload["embedding_config"] == {
        "provider_ref": "kb_embedding_provider",
        "api_path": "/embeddings",
    }


def test_model_provider_check_and_discover_endpoints(
    api_env: dict[str, object],
) -> None:
    client = _client(api_env)
    headers = _login_headers(client)

    with MockHttpApiServer(
        {
            "/v1/models": lambda request: {
                "data": [
                    {"id": "gpt-4.1"},
                    {"id": "gpt-5.2"},
                ]
            }
        }
    ) as server:
        payload = {
            "api_mode": "openai_compatible",
            "api_key": "test-openai-key",
            "api_host": f"{server.base_url}/v1",
            "api_path": "/chat/completions",
            "network_compatibility": True,
        }

        check_response = client.post(
            "/api/v1/capabilities/model-providers/check",
            headers=headers,
            json=payload,
        )
        assert check_response.status_code == 200
        assert check_response.json()["ok"] is True
        assert check_response.json()["model_count"] == 2
        assert (
            check_response.json()["models_endpoint"] == f"{server.base_url}/v1/models"
        )

        discover_response = client.post(
            "/api/v1/capabilities/model-providers/discover-models",
            headers=headers,
            json=payload,
        )
        assert discover_response.status_code == 200
        assert discover_response.json()["models"] == ["gpt-4.1", "gpt-5.2"]


def test_identity_and_profile_api_flow(api_env: dict[str, object]) -> None:
    client = _client(api_env)
    headers = _login_headers(client)

    roles_response = client.get("/api/v1/roles", headers=headers)
    assert roles_response.status_code == 200
    roles = roles_response.json()
    viewer_role = next(role for role in roles if role["code"] == "viewer")

    permissions_response = client.get("/api/v1/permissions", headers=headers)
    assert permissions_response.status_code == 200
    assert any(item["code"] == "users:read" for item in permissions_response.json())

    profile_response = client.get("/api/v1/profile", headers=headers)
    assert profile_response.status_code == 200
    assert profile_response.json()["user"]["username"] == "ops-admin"
    current_user_id = profile_response.json()["user"]["id"]

    create_api_key_response = client.post(
        "/api/v1/profile/api-keys",
        headers=headers,
        json={"name": "Smoke Key"},
    )
    assert create_api_key_response.status_code == 200
    created_api_key = create_api_key_response.json()
    api_key_id = created_api_key["api_key"]["id"]
    assert created_api_key["plain_text_key"].startswith("agk_")

    create_user_response = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "viewer-user",
            "display_name": "Viewer User",
            "password": "viewer-pass-2026",
            "status": "active",
            "is_superuser": False,
            "role_ids": [viewer_role["id"]],
            "direct_permissions": [],
        },
    )
    assert create_user_response.status_code == 200
    created_user = create_user_response.json()
    user_id = created_user["id"]

    list_users_response = client.get("/api/v1/users", headers=headers)
    assert list_users_response.status_code == 200
    assert any(item["id"] == user_id for item in list_users_response.json())

    get_user_response = client.get(f"/api/v1/users/{user_id}", headers=headers)
    assert get_user_response.status_code == 200
    assert get_user_response.json()["username"] == "viewer-user"

    update_user_response = client.put(
        f"/api/v1/users/{user_id}",
        headers=headers,
        json={
            "display_name": "Viewer User Updated",
            "status": "active",
            "is_superuser": False,
            "role_ids": [viewer_role["id"]],
            "direct_permissions": [
                {
                    "permission_code": "knowledge:read",
                    "effect": "allow",
                },
            ],
        },
    )
    assert update_user_response.status_code == 200
    assert update_user_response.json()["display_name"] == "Viewer User Updated"
    assert any(
        item["permission"]["code"] == "knowledge:read"
        for item in update_user_response.json()["direct_permissions"]
    )

    delete_self_response = client.delete(
        f"/api/v1/users/{current_user_id}", headers=headers
    )
    assert delete_self_response.status_code == 400
    assert "current signed-in user" in delete_self_response.json()["detail"]

    delete_user_response = client.delete(f"/api/v1/users/{user_id}", headers=headers)
    assert delete_user_response.status_code == 200
    assert delete_user_response.json()["deleted"] is True

    list_users_after_delete_response = client.get("/api/v1/users", headers=headers)
    assert list_users_after_delete_response.status_code == 200
    assert all(
        item["id"] != user_id for item in list_users_after_delete_response.json()
    )

    delete_api_key_response = client.delete(
        f"/api/v1/profile/api-keys/{api_key_id}",
        headers=headers,
    )
    assert delete_api_key_response.status_code == 204


def test_chat_session_list_returns_sidebar_friendly_summaries(
    api_env: dict[str, object],
) -> None:
    client = _client(api_env)
    headers = _login_headers(client)

    create_chatbot_response = client.post(
        "/api/v1/chatbots",
        headers=headers,
        json={
            "name": "Sidebar Bot",
            "description": "Test bot",
            "system_prompt": "Help the user.",
            "model_binding": {},
            "mcp_bindings": [],
            "function_bindings": [],
            "knowledge_bindings": [],
            "max_turns": 20,
        },
    )
    assert create_chatbot_response.status_code == 200
    chatbot_id = create_chatbot_response.json()["id"]

    first_session_response = client.post(
        "/api/v1/chat/sessions",
        headers=headers,
        json={"chatbot_id": chatbot_id},
    )
    assert first_session_response.status_code == 200
    first_session_id = first_session_response.json()["id"]

    second_session_response = client.post(
        "/api/v1/chat/sessions",
        headers=headers,
        json={"chatbot_id": chatbot_id},
    )
    assert second_session_response.status_code == 200
    second_session_id = second_session_response.json()["id"]

    async def seed_messages() -> None:
        async with _session_factory(api_env)() as session:
            session.add_all(
                [
                    ChatMessage(
                        session_id=first_session_id,
                        role="user",
                        content="帮我做一个去东京的三日旅行计划",
                        seq=1,
                    ),
                    ChatMessage(
                        session_id=first_session_id,
                        role="assistant",
                        content="当然，我先给你一个三天两晚的安排。",
                        seq=2,
                    ),
                ]
            )
            first_session = await session.get(ChatSession, first_session_id)
            assert first_session is not None
            first_session.updated_at = datetime.now(timezone.utc) + timedelta(minutes=5)
            await session.commit()

    asyncio.run(seed_messages())

    list_response = client.get(
        f"/api/v1/chat/sessions?chatbot_id={chatbot_id}",
        headers=headers,
    )
    assert list_response.status_code == 200

    sessions = list_response.json()
    first_summary = next(item for item in sessions if item["id"] == first_session_id)
    second_summary = next(item for item in sessions if item["id"] == second_session_id)

    assert first_summary["title"] == "帮我做一个去东京的三日旅行计划"
    assert first_summary["last_message_preview"] == "当然，我先给你一个三天两晚的安排。"
    assert first_summary["message_count"] == 2
    assert second_summary["title"] == "新对话"
    assert second_summary["last_message_preview"] is None
    assert second_summary["message_count"] == 0


def test_chat_session_branch_copies_prefix_messages(
    api_env: dict[str, object],
) -> None:
    client = _client(api_env)
    headers = _login_headers(client)

    create_chatbot_response = client.post(
        "/api/v1/chatbots",
        headers=headers,
        json={
            "name": "Branch Bot",
            "description": "Test bot",
            "system_prompt": "Help the user.",
            "model_binding": {},
            "mcp_bindings": [],
            "function_bindings": [],
            "knowledge_bindings": [],
            "max_turns": 20,
        },
    )
    assert create_chatbot_response.status_code == 200
    chatbot_id = create_chatbot_response.json()["id"]

    source_session_response = client.post(
        "/api/v1/chat/sessions",
        headers=headers,
        json={"chatbot_id": chatbot_id},
    )
    assert source_session_response.status_code == 200
    source_session_id = source_session_response.json()["id"]

    async def seed_messages() -> None:
        async with _session_factory(api_env)() as session:
            session.add_all(
                [
                    ChatMessage(
                        session_id=source_session_id,
                        role="user",
                        content="第一轮问题",
                        seq=1,
                    ),
                    ChatMessage(
                        session_id=source_session_id,
                        role="assistant",
                        content="第一轮回答",
                        seq=2,
                    ),
                    ChatMessage(
                        session_id=source_session_id,
                        role="user",
                        content="第二轮问题",
                        seq=3,
                    ),
                    ChatMessage(
                        session_id=source_session_id,
                        role="assistant",
                        content="第二轮回答",
                        seq=4,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed_messages())

    branch_response = client.post(
        f"/api/v1/chat/sessions/{source_session_id}/branch",
        headers=headers,
        json={"before_seq": 3},
    )
    assert branch_response.status_code == 200
    branched_session = branch_response.json()
    assert branched_session["id"] != source_session_id
    assert branched_session["chatbot_id"] == chatbot_id
    assert branched_session["message_count"] == 2
    assert branched_session["status"] == "active"

    messages_response = client.get(
        f"/api/v1/chat/sessions/{branched_session['id']}/messages",
        headers=headers,
    )
    assert messages_response.status_code == 200
    assert [
        (item["seq"], item["role"], item["content"])
        for item in messages_response.json()
    ] == [
        (1, "user", "第一轮问题"),
        (2, "assistant", "第一轮回答"),
    ]


def test_chat_session_can_rename_and_delete(
    api_env: dict[str, object],
) -> None:
    client = _client(api_env)
    headers = _login_headers(client)

    create_chatbot_response = client.post(
        "/api/v1/chatbots",
        headers=headers,
        json={
            "name": "Rename Bot",
            "description": "Test bot",
            "system_prompt": "Help the user.",
            "model_binding": {},
            "mcp_bindings": [],
            "function_bindings": [],
            "knowledge_bindings": [],
            "max_turns": 20,
        },
    )
    assert create_chatbot_response.status_code == 200
    chatbot_id = create_chatbot_response.json()["id"]

    session_response = client.post(
        "/api/v1/chat/sessions",
        headers=headers,
        json={"chatbot_id": chatbot_id},
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]

    rename_response = client.patch(
        f"/api/v1/chat/sessions/{session_id}",
        headers=headers,
        json={"title": "东京三日游细化版"},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["title"] == "东京三日游细化版"

    list_response = client.get(
        f"/api/v1/chat/sessions?chatbot_id={chatbot_id}",
        headers=headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["title"] == "东京三日游细化版"

    delete_response = client.delete(
        f"/api/v1/chat/sessions/{session_id}",
        headers=headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "session_id": session_id}

    list_after_delete_response = client.get(
        f"/api/v1/chat/sessions?chatbot_id={chatbot_id}",
        headers=headers,
    )
    assert list_after_delete_response.status_code == 200
    assert list_after_delete_response.json() == []




