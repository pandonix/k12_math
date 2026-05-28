"""Migration runner behavior — atomic apply, idempotency, fail-loud on bad SQL."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, create_engine, text

from backend.db import run_migrations


def _table_names(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        return {
            row.name
            for row in session.exec(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).all()
        }


def _applied_versions(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        return {
            row.version
            for row in session.exec(text("SELECT version FROM schema_migrations")).all()
        }


def test_initial_migration_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "math.db"
    applied = run_migrations(db_path=db_path)

    assert applied == ["0001"]
    tables = _table_names(db_path)
    for required in (
        "knowledge_points",
        "questions",
        "attempts",
        "mistakes",
        "mistake_diagnoses",
        "personal_weaknesses",
        "schema_migrations",
    ):
        assert required in tables, f"missing table {required}"


def test_run_migrations_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "math.db"
    first = run_migrations(db_path=db_path)
    second = run_migrations(db_path=db_path)

    assert first == ["0001"]
    assert second == []


def test_failed_migration_rolls_back_atomically(tmp_path: Path) -> None:
    """A migration that fails mid-script must leave neither partial schema
    nor a schema_migrations row behind — otherwise reruns would skip the
    broken version and the DB would silently diverge from the spec."""
    bad_dir = tmp_path / "migrations"
    bad_dir.mkdir()
    (bad_dir / "0001_bad.sql").write_text(
        "CREATE TABLE good (id INTEGER PRIMARY KEY);\n"
        "INVALID SQL STATEMENT HERE;\n"
        "CREATE TABLE never_created (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "math.db"

    with pytest.raises(RuntimeError, match="0001_bad.sql failed"):
        run_migrations(db_path=db_path, migrations_dir=bad_dir)

    tables = _table_names(db_path)
    assert "good" not in tables
    assert "never_created" not in tables
    assert _applied_versions(db_path) == set()
