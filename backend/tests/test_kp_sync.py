from __future__ import annotations

import json

from sqlmodel import Session, create_engine, text

from backend.db import run_migrations
from backend.services.kp_sync import DEFAULT_MD_PATH, load_knowledge_points, sync_knowledge_points


def test_knowledge_markdown_keeps_legacy_ids_unique() -> None:
    items = load_knowledge_points(DEFAULT_MD_PATH)

    assert len(items) == 56
    assert len({item.id for item in items}) == len(items)


def test_sync_writes_expected_knowledge_points(tmp_path) -> None:
    db_path = tmp_path / "math.db"
    run_migrations(db_path=db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    with Session(engine) as session:
        result = sync_knowledge_points(session)
        count = session.exec(text("SELECT COUNT(*) AS count FROM knowledge_points")).one().count
        first = session.exec(
            text("SELECT tags_json FROM knowledge_points ORDER BY order_index LIMIT 1")
        ).one()

    assert result.parsed == 56
    assert result.inserted == 56
    assert count == 56
    assert isinstance(json.loads(first.tags_json), list)
