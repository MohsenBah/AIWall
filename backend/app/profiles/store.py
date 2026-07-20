# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Profile persistence and CRUD operations."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.profiles.models import PROFILE_ROLES, ProfileRow
from app.storage.database import session_factory


@dataclass(frozen=True)
class Profile:
    id: int
    name: str
    role: str
    api_key_hash: str | None
    daily_request_limit: int | None
    daily_token_limit: int | None
    daily_cost_limit: float | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ProfileError(ValueError):
    """Raised for invalid profile operations."""


def hash_api_key(api_key: str) -> str:
    """Hash a profile API key for storage (never store plaintext)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _to_dataclass(row: ProfileRow) -> Profile:
    return Profile(
        id=row.id,
        name=row.name,
        role=row.role,
        api_key_hash=row.api_key_hash,
        daily_request_limit=row.daily_request_limit,
        daily_token_limit=row.daily_token_limit,
        daily_cost_limit=row.daily_cost_limit,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_role(role: str) -> None:
    if role not in PROFILE_ROLES:
        raise ProfileError(
            f"Invalid profile role {role!r}; expected one of {sorted(PROFILE_ROLES)}"
        )


class ProfileStore:
    def __init__(self, engine: Engine):
        self._engine = engine
        self._session_factory = session_factory(engine)

    def create(
        self,
        *,
        name: str,
        role: str = "adult",
        api_key_hash: str | None = None,
        daily_request_limit: int | None = None,
        daily_token_limit: int | None = None,
        daily_cost_limit: float | None = None,
        enabled: bool = True,
    ) -> Profile:
        cleaned = name.strip()
        if not cleaned:
            raise ProfileError("Profile name is required")
        _validate_role(role)

        row = ProfileRow(
            name=cleaned,
            role=role,
            api_key_hash=api_key_hash,
            daily_request_limit=daily_request_limit,
            daily_token_limit=daily_token_limit,
            daily_cost_limit=daily_cost_limit,
            enabled=enabled,
        )
        with self._session_factory() as session:
            existing = session.scalars(
                select(ProfileRow).where(ProfileRow.name == cleaned)
            ).first()
            if existing is not None:
                raise ProfileError(f"Profile already exists: {cleaned}")
            if api_key_hash:
                hash_owner = session.scalars(
                    select(ProfileRow).where(ProfileRow.api_key_hash == api_key_hash)
                ).first()
                if hash_owner is not None:
                    raise ProfileError("API key hash is already assigned to another profile")
            session.add(row)
            session.commit()
            session.refresh(row)
            return _to_dataclass(row)

    def get(self, profile_id: int) -> Profile | None:
        with self._session_factory() as session:
            row = session.get(ProfileRow, profile_id)
            return _to_dataclass(row) if row else None

    def get_by_name(self, name: str) -> Profile | None:
        with self._session_factory() as session:
            row = session.scalars(
                select(ProfileRow).where(ProfileRow.name == name.strip())
            ).first()
            return _to_dataclass(row) if row else None

    def get_by_api_key_hash(self, api_key_hash: str) -> Profile | None:
        with self._session_factory() as session:
            row = session.scalars(
                select(ProfileRow).where(ProfileRow.api_key_hash == api_key_hash)
            ).first()
            return _to_dataclass(row) if row else None

    def list(self) -> list[Profile]:
        with self._session_factory() as session:
            rows = session.scalars(select(ProfileRow).order_by(ProfileRow.id)).all()
            return [_to_dataclass(row) for row in rows]

    def update(
        self,
        profile_id: int,
        *,
        name: str | None = None,
        role: str | None = None,
        api_key_hash: str | None = None,
        clear_api_key_hash: bool = False,
        daily_request_limit: int | None = None,
        daily_token_limit: int | None = None,
        daily_cost_limit: float | None = None,
        clear_daily_request_limit: bool = False,
        clear_daily_token_limit: bool = False,
        clear_daily_cost_limit: bool = False,
        enabled: bool | None = None,
    ) -> Profile:
        with self._session_factory() as session:
            row = session.get(ProfileRow, profile_id)
            if row is None:
                raise ProfileError(f"Profile not found: {profile_id}")

            if name is not None:
                cleaned = name.strip()
                if not cleaned:
                    raise ProfileError("Profile name is required")
                clash = session.scalars(
                    select(ProfileRow).where(
                        ProfileRow.name == cleaned,
                        ProfileRow.id != profile_id,
                    )
                ).first()
                if clash is not None:
                    raise ProfileError(f"Profile already exists: {cleaned}")
                row.name = cleaned

            if role is not None:
                _validate_role(role)
                row.role = role

            if clear_api_key_hash:
                row.api_key_hash = None
            elif api_key_hash is not None:
                hash_owner = session.scalars(
                    select(ProfileRow).where(
                        ProfileRow.api_key_hash == api_key_hash,
                        ProfileRow.id != profile_id,
                    )
                ).first()
                if hash_owner is not None:
                    raise ProfileError("API key hash is already assigned to another profile")
                row.api_key_hash = api_key_hash

            if clear_daily_request_limit:
                row.daily_request_limit = None
            elif daily_request_limit is not None:
                row.daily_request_limit = daily_request_limit

            if clear_daily_token_limit:
                row.daily_token_limit = None
            elif daily_token_limit is not None:
                row.daily_token_limit = daily_token_limit

            if clear_daily_cost_limit:
                row.daily_cost_limit = None
            elif daily_cost_limit is not None:
                row.daily_cost_limit = daily_cost_limit

            if enabled is not None:
                row.enabled = enabled

            row.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
            return _to_dataclass(row)

    def delete(self, profile_id: int) -> bool:
        with self._session_factory() as session:
            row = session.get(ProfileRow, profile_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def issue_api_key(self, profile_id: int) -> str:
        """Generate a new API key for a profile.

        Returns the plaintext key once. Only the SHA-256 hash is stored.
        """
        plaintext = "aiwall_pk_" + secrets.token_urlsafe(32)
        key_hash = hash_api_key(plaintext)
        self.update(profile_id, api_key_hash=key_hash)
        return plaintext
