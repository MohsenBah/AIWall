"""AIWall FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from app import __version__
from app.audit.writer import AuditWriter
from app.config import AIWallConfig, load_config, resolve_config_path
from app.policies.engine import PolicyEngine
from app.proxy.routes import router as proxy_router
from app.proxy.pricing import CostEstimator, resolve_prices_path
from app.storage.database import create_engine_from_config, init_db

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0, read=300.0, write=60.0, pool=10.0)


def _init_storage(config: AIWallConfig) -> tuple[Any, AuditWriter]:
    engine = create_engine_from_config(config)
    init_db(engine)
    return engine, AuditWriter(engine)


def create_app(
    config_path: Path | str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    resolved_path = resolve_config_path(config_path)
    config = load_config(resolved_path)
    engine, audit_writer = _init_storage(config)
    prices_path = resolve_prices_path(resolved_path, config.pricing.file)
    cost_estimator = CostEstimator(prices_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = load_config(resolved_path)
        try:
            if http_client is not None:
                yield
            else:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    app.state.http_client = client
                    yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="AIWall",
        description="Self-hosted AI security gateway.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.config_path = resolved_path
    app.state.config = config
    app.state.engine = engine
    app.state.audit_writer = audit_writer
    app.state.policy_engine = PolicyEngine(resolved_path)
    app.state.cost_estimator = cost_estimator
    if http_client is not None:
        app.state.http_client = http_client

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        config: AIWallConfig = app.state.config
        return {
            "status": "ok",
            "version": __version__,
            "service": "aiwall",
            "config_path": str(app.state.config_path),
            "providers": len(config.providers),
            "policies": len(config.policies),
        }

    app.include_router(proxy_router)
    return app


app = create_app()
