"""AIWall FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app import __version__
from app.config import AIWallConfig, load_config, resolve_config_path


def create_app(config_path: Path | str | None = None) -> FastAPI:
    resolved_path = resolve_config_path(config_path)
    config = load_config(resolved_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = load_config(resolved_path)
        yield

    app = FastAPI(
        title="AIWall",
        description="Self-hosted AI security gateway.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.config_path = resolved_path
    app.state.config = config

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

    return app


app = create_app()
