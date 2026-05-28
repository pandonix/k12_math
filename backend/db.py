from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from sqlmodel import Session, create_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "math.db"
MIGRATIONS_DIR = BACKEND_ROOT / "migrations"


def get_db_path() -> Path:
    return Path(os.environ.get("MATH_DB_PATH", DEFAULT_DB_PATH)).expanduser().resolve()


def get_database_url(db_path: Path | None = None) -> str:
    path = db_path or get_db_path()
    return f"sqlite:///{path}"


engine = create_engine(
    get_database_url(),
    connect_args={"check_same_thread": False},
)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def _backup_db(db_path: Path, version: str) -> None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.name}.before-{version}.{stamp}.bak")
    shutil.copy2(db_path, backup_path)


def run_migrations(
    db_path: Path | None = None,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> list[str]:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    migration_files = sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    applied_now: list[str] = []

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version TEXT PRIMARY KEY,
              applied_at DATETIME NOT NULL
            )
            """
        )
        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }

    for migration in migration_files:
        version = migration.name.split("_", 1)[0]
        if version in applied:
            continue

        _backup_db(path, version)
        script = migration.read_text(encoding="utf-8")
        applied_at = datetime.now(timezone.utc).isoformat()
        transaction_script = "\n".join(
            [
                "BEGIN;",
                script,
                (
                    "INSERT INTO schema_migrations(version, applied_at) "
                    f"VALUES ('{version}', '{applied_at}');"
                ),
                "COMMIT;",
            ]
        )
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                conn.executescript(transaction_script)
            except Exception:
                conn.rollback()
                raise
        applied_now.append(version)

    return applied_now
