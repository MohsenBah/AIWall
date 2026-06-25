"""SQLite database engine and session management."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.audit.models import Base
from app.config import AIWallConfig


def sqlite_path_from_store(store_url: str) -> Path:
    if not store_url.startswith("sqlite:///"):
        raise ValueError(f"Invalid SQLite store URL: {store_url}")
    path_part = store_url.removeprefix("sqlite:///")
    return Path(path_part)


def create_engine_from_config(config: AIWallConfig) -> Engine:
    store_url = config.logging.store
    if not store_url.startswith("sqlite:"):
        raise ValueError(f"Only SQLite audit stores are supported in MVP: {store_url}")

    db_path = sqlite_path_from_store(store_url)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        store_url,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
