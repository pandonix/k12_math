from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, create_engine, text

from backend.db import run_migrations
from backend.schemas import AttemptCreate, NamedNodeInput, QuestionCreate, WeightedKpInput
from backend.services.kp_sync import sync_knowledge_points
from backend.services.practice_store import create_attempt
from backend.services.question_store import create_question
from backend.services.stats_store import heatmap, personal_pitfalls, trend, type_radar, weak_top, weakness_detail


def _session(tmp_path: Path) -> Session:
    db_path = tmp_path / "math.db"
    run_migrations(db_path=db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    session = Session(engine)
    sync_knowledge_points(session)
    return session


def _seed_evidence(session: Session) -> int:
    kp_id = session.exec(
        text("SELECT id FROM knowledge_points ORDER BY order_index LIMIT 1")
    ).one().id
    question = create_question(
        session,
        QuestionCreate(
            source="M4 学情样题",
            format_id=1,
            stem_md="已知集合 A，判断元素关系。",
            answer_md="属于",
            kp_ids=[WeightedKpInput(id=kp_id, is_primary=True)],
            patterns=[NamedNodeInput(name="集合元素关系判定", is_primary=True)],
            skills=[NamedNodeInput(name="符号翻译")],
            pitfalls=[NamedNodeInput(name="属于号和包含号混淆")],
        ),
    )
    create_attempt(
        session,
        AttemptCreate(
            question_id=question.id,
            is_correct=False,
            user_answer_md="误写为包含",
        ),
    )
    create_attempt(session, AttemptCreate(question_id=question.id, is_correct=True))
    return question.id


def test_stats_store_surfaces_personal_weakness_evidence(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        question_id = _seed_evidence(session)

        top_items = weak_top(session)
        detail = weakness_detail(session, top_items[0].id)
        heatmap_items = heatmap(session)
        type_items = type_radar(session)
        pitfall_items = personal_pitfalls(session)
        trend_items = trend(session, period="week")

    assert top_items
    assert top_items[0].evidence_count >= 1
    assert top_items[0].score > 0
    assert detail.evidence
    assert detail.related_questions[0].id == question_id
    assert detail.suggested_target["mode"] == "weakness"
    assert heatmap_items[0].wrong_count == 1
    assert type_items[0].wrong_count == 1
    assert pitfall_items[0].target_type == "pitfall"
    assert len(trend_items) == 7
    assert sum(point.wrong_count for point in trend_items) == 1
