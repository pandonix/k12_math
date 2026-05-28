"""Schema drift guard: SQLModel column set must match the migrated DB (PLAN §5.3.5).

Migrations are the source of truth; models.py is the runtime query surface.
This catches accidental drift in either direction before it reaches a real DB.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine

import backend.models  # noqa: F401 — import registers SQLModel tables on metadata
from backend.db import run_migrations


_TYPE_PATTERNS = (
    ("INTEGER", ("INT", "BOOL")),
    ("TEXT", ("CHAR", "TEXT", "STRING", "CLOB")),
    ("REAL", ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL")),
    ("DATETIME", ("DATE", "TIME", "TIMESTAMP")),
    ("BLOB", ("BLOB", "BINARY")),
)


def _type_family(type_obj: object) -> str:
    """Coarse type bucket. SQLModel `str` → VARCHAR, migration declares TEXT;
    both have TEXT affinity in SQLite, so we collapse to families."""
    raw = re.sub(r"\(.*?\)", "", str(type_obj)).strip().upper()
    for family, needles in _TYPE_PATTERNS:
        if any(needle in raw for needle in needles):
            return family
    return raw


def test_sqlmodel_tables_match_migrated_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "math.db"
    run_migrations(db_path=db_path)
    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    db_table_names = set(inspector.get_table_names())

    errors: list[str] = []

    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in db_table_names:
            errors.append(
                f"{table_name}: declared in models.py but no matching table in migrations"
            )
            continue

        model_cols = {col.name: _type_family(col.type) for col in table.columns}
        db_cols = {
            col["name"]: _type_family(col["type"])
            for col in inspector.get_columns(table_name)
        }

        only_in_model = sorted(set(model_cols) - set(db_cols))
        only_in_db = sorted(set(db_cols) - set(model_cols))
        if only_in_model or only_in_db:
            errors.append(
                f"{table_name}: column drift — only_in_model={only_in_model}, "
                f"only_in_db={only_in_db}"
            )
            continue

        type_diffs = [
            f"{name}(model={model_cols[name]}, db={db_cols[name]})"
            for name in sorted(model_cols)
            if model_cols[name] != db_cols[name]
        ]
        if type_diffs:
            errors.append(f"{table_name}: type drift — {', '.join(type_diffs)}")

    if errors:
        pytest.fail("schema drift detected:\n" + "\n".join(f"  - {e}" for e in errors))
