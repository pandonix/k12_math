from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlmodel import Session, create_engine, text

from backend.db import run_migrations
from backend.schemas import NamedNodeInput, PatternCreate, QuestionCreate, WeightedKpInput
from backend.services.importers.docx_handout import import_docx_handout
from backend.services.kp_sync import sync_knowledge_points
from backend.services.question_store import create_question, list_questions


def _session(tmp_path: Path) -> Session:
    db_path = tmp_path / "math.db"
    run_migrations(db_path=db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    session = Session(engine)
    sync_knowledge_points(session)
    return session


def test_create_question_links_graph_nodes_and_filters_by_kp(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        kp_id = session.exec(
            text("SELECT id FROM knowledge_points ORDER BY order_index LIMIT 1")
        ).one().id

        created = create_question(
            session,
            QuestionCreate(
                source="M1测试-第1题",
                format_id=1,
                difficulty=2,
                stem_md="已知集合 $A=\\{1,2\\}$，判断 $1\\in A$.",
                answer_md="是",
                solution_md="1 是集合 A 中的元素。",
                kp_ids=[WeightedKpInput(id=kp_id, weight=1, is_primary=True)],
                patterns=[NamedNodeInput(name="集合元素判定", is_primary=True)],
                skills=[NamedNodeInput(name="符号识别")],
                pitfalls=[NamedNodeInput(name="混淆属于和包含")],
                tags=["易错型"],
            ),
        )

        listed = list_questions(session, kp=kp_id)

    assert created.id
    assert created.knowledge_points[0].id == kp_id
    assert created.patterns[0].name == "集合元素判定"
    assert created.skills[0].name == "符号识别"
    assert created.pitfalls[0].name == "混淆属于和包含"
    assert created.tags == ["易错型"]
    assert listed.total == 1
    assert listed.items[0].id == created.id


def test_create_question_rejects_exact_duplicate_stem(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        payload = QuestionCreate(stem_md="同一道题", answer_md="A")
        create_question(session, payload)
        with pytest.raises(HTTPException) as exc:
            create_question(session, payload)

    assert exc.value.status_code == 409


def test_docx_import_returns_reviewable_preview() -> None:
    preview = import_docx_handout()

    assert preview.paragraph_count == 380
    assert preview.type_count == 8
    assert preview.question_count == 24
    assert preview.patterns[0]["name"].startswith("题型一")
    assert preview.questions[0].source.startswith("题型一")
