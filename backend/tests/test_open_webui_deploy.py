# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import write_test_config


@pytest.mark.asyncio
async def test_cors_headers_when_enabled(tmp_path: Path) -> None:
    import httpx

    from app.main import create_app

    config_path = write_test_config(
        tmp_path,
        policies_block="",
        extra_yaml="""
cors:
  enabled: true
  allow_origins:
    - "http://localhost:3000"
""".strip(),
    )
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    )
    app = create_app(config_path=config_path, http_client=http_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preflight = await client.options(
            "/v1/models",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        health = await client.get(
            "/healthz",
            headers={"Origin": "http://localhost:3000"},
        )

    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert health.status_code == 200
    assert health.headers.get("access-control-allow-origin") == "http://localhost:3000"
    await http_client.aclose()


def test_issue_profile_key_script(tmp_path: Path) -> None:
    import importlib.util

    from sqlalchemy import create_engine

    from app.profiles.store import ProfileStore
    from app.storage.database import init_db

    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "issue_profile_key.py"
    spec = importlib.util.spec_from_file_location("issue_profile_key", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    db_path = tmp_path / "aiwall.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    rc = module.main(
        [
            "--db",
            db_url,
            "--name",
            "Kid",
            "--role",
            "child",
            "--daily-request-limit",
            "10",
        ]
    )
    assert rc == 0

    engine = create_engine(db_url)
    init_db(engine)
    store = ProfileStore(engine)
    profile = store.get_by_name("Kid")
    assert profile is not None
    assert profile.role == "child"
    assert profile.daily_request_limit == 10
    assert profile.api_key_hash is not None
