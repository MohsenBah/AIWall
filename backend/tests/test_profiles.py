# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.profiles import PROFILE_ROLES, ProfileError, ProfileStore, hash_api_key
from app.storage.database import init_db


@pytest.fixture
def profile_store(tmp_path: Path) -> ProfileStore:
    db_path = tmp_path / "profiles.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)
    return ProfileStore(engine)


def test_init_db_creates_profiles_table(tmp_path: Path) -> None:
    db_path = tmp_path / "aiwall.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)

    with engine.connect() as conn:
        tables = {
            row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(profiles)"))}

    assert "profiles" in tables
    assert {
        "id",
        "name",
        "role",
        "api_key_hash",
        "daily_request_limit",
        "daily_token_limit",
        "daily_cost_limit",
        "enabled",
        "created_at",
        "updated_at",
    } <= columns


def test_profile_crud_create_get_list_update_delete(profile_store: ProfileStore) -> None:
    created = profile_store.create(
        name="Alex",
        role="child",
        daily_request_limit=50,
        daily_token_limit=100_000,
        daily_cost_limit=1.5,
    )
    assert created.id > 0
    assert created.name == "Alex"
    assert created.role == "child"
    assert created.daily_request_limit == 50
    assert created.daily_token_limit == 100_000
    assert created.daily_cost_limit == 1.5
    assert created.enabled is True
    assert created.api_key_hash is None

    fetched = profile_store.get(created.id)
    assert fetched is not None
    assert fetched.name == "Alex"

    by_name = profile_store.get_by_name("Alex")
    assert by_name is not None
    assert by_name.id == created.id

    listed = profile_store.list()
    assert len(listed) == 1
    assert listed[0].id == created.id

    key_hash = hash_api_key("aiwall-profile-test-key")
    updated = profile_store.update(
        created.id,
        name="Alex-Child",
        role="child",
        api_key_hash=key_hash,
        daily_request_limit=25,
        enabled=False,
    )
    assert updated.name == "Alex-Child"
    assert updated.api_key_hash == key_hash
    assert updated.daily_request_limit == 25
    assert updated.enabled is False

    by_hash = profile_store.get_by_api_key_hash(key_hash)
    assert by_hash is not None
    assert by_hash.id == created.id

    assert profile_store.delete(created.id) is True
    assert profile_store.get(created.id) is None
    assert profile_store.delete(created.id) is False


def test_profile_rejects_invalid_role(profile_store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="Invalid profile role"):
        profile_store.create(name="Bad", role="toddler")


def test_profile_rejects_duplicate_name(profile_store: ProfileStore) -> None:
    profile_store.create(name="Sam", role="adult")
    with pytest.raises(ProfileError, match="already exists"):
        profile_store.create(name="Sam", role="child")


def test_profile_rejects_duplicate_api_key_hash(profile_store: ProfileStore) -> None:
    key_hash = hash_api_key("shared-key")
    profile_store.create(name="One", role="adult", api_key_hash=key_hash)
    with pytest.raises(ProfileError, match="already assigned"):
        profile_store.create(name="Two", role="child", api_key_hash=key_hash)


def test_profile_roles_include_family_defaults() -> None:
    assert {"adult", "child", "developer", "guest"} <= PROFILE_ROLES


def test_issue_api_key_stores_hash_only(profile_store: ProfileStore) -> None:
    profile = profile_store.create(name="KeyUser", role="adult")
    plaintext = profile_store.issue_api_key(profile.id)
    assert plaintext.startswith("aiwall_pk_")
    stored = profile_store.get(profile.id)
    assert stored is not None
    assert stored.api_key_hash == hash_api_key(plaintext)
    assert plaintext not in (stored.api_key_hash or "")


@pytest.mark.asyncio
async def test_app_exposes_profile_store(tmp_path: Path) -> None:
    import httpx
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    from tests.conftest import write_test_config

    config_path = write_test_config(tmp_path, "")
    mock_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    http_client = httpx.AsyncClient(transport=mock_transport)
    app = create_app(config_path=config_path, http_client=http_client)

    created = app.state.profile_store.create(name="Jamie", role="adult")
    assert app.state.profile_store.get(created.id) is not None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/healthz")

    assert health.status_code == 200
    assert health.json()["profiles"] == 1
    await http_client.aclose()
