from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, create_engine, text

from backend.db import run_migrations
from backend.schemas import ParsedMistakeInput, QuestionCreate, WeightedKpInput
from backend.services.intake_store import capabilities, commit_mistakes, commit_questions, parse_upload
from backend.services.kp_sync import sync_knowledge_points
from backend.schemas import IntakeParseRequest


def _session(tmp_path: Path) -> Session:
    db_path = tmp_path / "math.db"
    run_migrations(db_path=db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    session = Session(engine)
    sync_knowledge_points(session)
    return session


def test_manual_capabilities_are_local_first() -> None:
    caps = capabilities()

    assert caps.provider == "manual"
    assert caps.supports_handwriting is False
    assert caps.supports_pdf is True
    assert caps.supports_images is True


def test_parse_upload_returns_manual_pages(tmp_path: Path, monkeypatch) -> None:
    from backend.services import intake_store

    monkeypatch.setattr(intake_store, "UPLOAD_ROOT", tmp_path)
    upload_dir = tmp_path / "abc123"
    upload_dir.mkdir()
    (upload_dir / "page-1.png").write_bytes(b"fake")

    result = parse_upload(IntakeParseRequest(upload_id="abc123", schema_name="mistake"))

    assert result.provider == "manual"
    assert result.schema_name == "mistake"
    assert result.pages == [str(upload_dir / "page-1.png")]


def test_commit_questions_and_mistakes_reuse_question_hash(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        kp_id = session.exec(
            text("SELECT id FROM knowledge_points ORDER BY order_index LIMIT 1")
        ).one().id
        question = QuestionCreate(
            stem_md="M3 题干",
            answer_md="A",
            kp_ids=[WeightedKpInput(id=kp_id, is_primary=True)],
        )
        question_commit = commit_questions(session, [question])
        mistake_commit = commit_mistakes(
            session,
            [
                ParsedMistakeInput(
                    question=question,
                    user_answer_md="B",
                    is_correct=False,
                )
            ],
        )
        question_count = session.exec(text("SELECT COUNT(*) AS count FROM questions")).one().count
        attempt_count = session.exec(text("SELECT COUNT(*) AS count FROM attempts")).one().count

    assert question_commit.committed_n == 1
    assert mistake_commit.question_ids == question_commit.question_ids
    assert mistake_commit.attempt_ids
    assert question_count == 1
    assert attempt_count == 1
    # The commit response surfaces the personal-weakness nodes it just hit so the
    # frontend can render the "命中个人薄弱点 X/Y/Z" toast (PLAN §6.3.3).
    assert mistake_commit.matched_weaknesses
    assert mistake_commit.matched_weaknesses[0].target_type == "kp"


def test_commit_mistakes_is_atomic_on_failure(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        good = QuestionCreate(stem_md="可入库题")
        bad = QuestionCreate(stem_md="   ")  # blank stem → create_question raises
        try:
            commit_mistakes(
                session,
                [
                    ParsedMistakeInput(question=good, is_correct=False),
                    ParsedMistakeInput(question=bad, is_correct=False),
                ],
            )
        except Exception:
            pass
        question_count = session.exec(text("SELECT COUNT(*) AS count FROM questions")).one().count
        attempt_count = session.exec(text("SELECT COUNT(*) AS count FROM attempts")).one().count

    # The first (valid) mistake must not survive once the batch fails.
    assert question_count == 0
    assert attempt_count == 0
