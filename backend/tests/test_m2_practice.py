from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, create_engine, text

from backend.db import run_migrations
from backend.schemas import AttemptCreate, MistakePatch, NamedNodeInput, QuestionCreate, WeightedKpInput
from backend.services.kp_sync import sync_knowledge_points
from backend.services.practice_store import create_attempt, list_mistakes, patch_mistake
from backend.services.question_store import create_question


def _session(tmp_path: Path) -> Session:
    db_path = tmp_path / "math.db"
    run_migrations(db_path=db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    session = Session(engine)
    sync_knowledge_points(session)
    return session


def _question(session: Session) -> int:
    kp_id = session.exec(
        text("SELECT id FROM knowledge_points ORDER BY order_index LIMIT 1")
    ).one().id
    question = create_question(
        session,
        QuestionCreate(
            source="M2测试题",
            format_id=1,
            stem_md="判断 $1\\in A$。",
            answer_md="对",
            kp_ids=[WeightedKpInput(id=kp_id, is_primary=True)],
            patterns=[NamedNodeInput(name="集合元素判定", is_primary=True)],
            skills=[NamedNodeInput(name="符号识别")],
            pitfalls=[NamedNodeInput(name="混淆属于和包含")],
        ),
    )
    return question.id


def test_wrong_attempt_creates_mistake_diagnoses_and_weaknesses(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        question_id = _question(session)
        attempt = create_attempt(
            session,
            AttemptCreate(question_id=question_id, is_correct=False, user_answer_md="错答"),
        )
        mistakes = list_mistakes(session)
        weakness_count = session.exec(
            text("SELECT COUNT(*) AS count FROM personal_weaknesses")
        ).one().count

    assert attempt.id
    assert len(attempt.diagnoses) == 4
    assert mistakes.total == 1
    assert mistakes.items[0].wrong_count == 1
    assert weakness_count == 4
    assert mistakes.items[0].weaknesses[0].strength > 0


def test_repeated_wrong_and_correct_update_mistake_state(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        question_id = _question(session)
        create_attempt(session, AttemptCreate(question_id=question_id, is_correct=False))
        create_attempt(session, AttemptCreate(question_id=question_id, is_correct=False))
        create_attempt(session, AttemptCreate(question_id=question_id, is_correct=True))
        mistake = list_mistakes(session).items[0]

    assert mistake.wrong_count == 2
    assert mistake.mastered_streak == 1


def test_manual_master_event_hides_default_mistake_and_reduces_strength(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        question_id = _question(session)
        create_attempt(session, AttemptCreate(question_id=question_id, is_correct=False))
        before = session.exec(
            text("SELECT MAX(strength) AS strength FROM personal_weaknesses")
        ).one().strength
        patched = patch_mistake(session, question_id, MistakePatch(mastered=True))
        after = session.exec(
            text("SELECT MAX(strength) AS strength FROM personal_weaknesses")
        ).one().strength
        active = list_mistakes(session)
        all_mistakes = list_mistakes(session, include_mastered=True)

    assert patched.mastered_at is not None
    assert after < before
    assert active.total == 0
    assert all_mistakes.total == 1
