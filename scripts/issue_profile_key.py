# SPDX-FileCopyrightText: 2026 Mohsen Bah
# SPDX-License-Identifier: Apache-2.0
"""Create profiles and issue AIWall API keys for family / Open WebUI setups.

Examples:

  # Against a local SQLite audit DB:
  python scripts/issue_profile_key.py --db sqlite:///data/aiwall.db \\
      --name Kid --role child --daily-request-limit 50

  # Inside the AIWall container:
  docker compose -f deploy/examples/docker-compose.open-webui.yml exec aiwall \\
      python /app/scripts/issue_profile_key.py --db sqlite:///data/aiwall.db \\
      --name Kid --role child
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_backend_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    backend = repo_root / "backend"
    if backend.is_dir() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def main(argv: list[str] | None = None) -> int:
    _ensure_backend_on_path()

    from sqlalchemy import create_engine

    from app.profiles import PROFILE_ROLES, ProfileStore
    from app.storage.database import init_db

    parser = argparse.ArgumentParser(
        description="Create (or reuse) an AIWall profile and print a new API key."
    )
    parser.add_argument(
        "--db",
        required=True,
        help="SQLAlchemy SQLite URL, e.g. sqlite:///data/aiwall.db",
    )
    parser.add_argument("--name", required=True, help="Profile display name")
    parser.add_argument(
        "--role",
        default="adult",
        choices=sorted(PROFILE_ROLES),
        help="Profile role (default: adult)",
    )
    parser.add_argument("--daily-request-limit", type=int, default=None)
    parser.add_argument("--daily-token-limit", type=int, default=None)
    parser.add_argument("--daily-cost-limit", type=float, default=None)
    args = parser.parse_args(argv)

    if not args.db.startswith("sqlite:"):
        print("error: only sqlite:// URLs are supported", file=sys.stderr)
        return 2

    engine = create_engine(args.db, connect_args={"check_same_thread": False})
    init_db(engine)
    store = ProfileStore(engine)

    existing = store.get_by_name(args.name)
    if existing is None:
        profile = store.create(
            name=args.name,
            role=args.role,
            daily_request_limit=args.daily_request_limit,
            daily_token_limit=args.daily_token_limit,
            daily_cost_limit=args.daily_cost_limit,
        )
        created = True
    else:
        profile = store.update(
            existing.id,
            role=args.role,
            daily_request_limit=args.daily_request_limit,
            daily_token_limit=args.daily_token_limit,
            daily_cost_limit=args.daily_cost_limit,
        )
        created = False

    plaintext = store.issue_api_key(profile.id)
    action = "Created" if created else "Updated"
    print(f"{action} profile id={profile.id} name={profile.name!r} role={profile.role}")
    print("API key (shown once; store it in Open WebUI for this user):")
    print(plaintext)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
