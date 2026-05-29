from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlmodel import Session, text

from backend.schemas import (
    AttemptCreate,
    AttemptRead,
    DiagnosisInput,
    DiagnosisRead,
    MistakeListResponse,
    MistakePatch,
    MistakeRead,
    WeaknessRead,
)
from backend.services.question_store import get_question, utc_now
from backend.services.weakness_engine import apply_event, node_from_target, nodes_for_question


SUGGEST_MASTERED_MIN_STREAK = 3
SUGGEST_MASTERED_MIN_SPAN_HOURS = 24


def create_attempt(session: Session, payload: AttemptCreate, commit: bool = True) -> AttemptRead:
    get_question(session, payload.question_id)
    attempted_at = (payload.attempted_at or datetime.now(timezone.utc)).isoformat()
    result = session.exec(
        text(
            """
            INSERT INTO attempts(
              question_id, is_correct, self_rating, time_spent_sec, user_answer_md,
              answer_image_path, source, attempted_at
            )
            VALUES (
              :question_id, :is_correct, :self_rating, :time_spent_sec, :user_answer_md,
              :answer_image_path, :source, :attempted_at
            )
            """
        ),
        params={
            "question_id": payload.question_id,
            "is_correct": 1 if payload.is_correct else 0,
            "self_rating": payload.self_rating,
            "time_spent_sec": payload.time_spent_sec,
            "user_answer_md": payload.user_answer_md,
            "answer_image_path": payload.answer_image_path,
            "source": payload.source,
            "attempted_at": attempted_at,
        },
    )
    attempt_id = int(result.lastrowid)
    if payload.is_correct:
        _mark_correct(session, payload.question_id, attempt_id)
        for node in nodes_for_question(session, payload.question_id):
            apply_event(session, node, "correct")
    else:
        _mark_wrong(session, payload.question_id, attempt_id, attempted_at)
        diagnoses = payload.diagnoses or _rule_diagnoses(session, payload.question_id)
        for diagnosis in diagnoses:
            _insert_diagnosis(session, attempt_id, diagnosis)
            node = node_from_target(session, diagnosis.target_type, diagnosis.target_id, diagnosis.custom_label)
            apply_event(session, node, "wrong")
    if commit:
        session.commit()
    return get_attempt(session, attempt_id)


def get_attempt(session: Session, attempt_id: int) -> AttemptRead:
    row = session.exec(
        text("SELECT * FROM attempts WHERE id = :attempt_id"),
        params={"attempt_id": attempt_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return AttemptRead(
        id=row.id,
        question_id=row.question_id,
        is_correct=bool(row.is_correct),
        self_rating=row.self_rating,
        time_spent_sec=row.time_spent_sec,
        user_answer_md=row.user_answer_md,
        answer_image_path=row.answer_image_path,
        source=row.source,
        attempted_at=row.attempted_at,
        diagnoses=list_diagnoses(session, attempt_id),
    )


def list_mistakes(session: Session, include_mastered: bool = False) -> MistakeListResponse:
    where = "1 = 1" if include_mastered else "mastered_at IS NULL"
    rows = session.exec(
        text(f"SELECT * FROM mistakes WHERE {where} ORDER BY last_wrong_at DESC")
    ).all()
    items = [_mistake_read(session, row.question_id) for row in rows]
    return MistakeListResponse(total=len(items), items=items)


def patch_mistake(session: Session, question_id: int, payload: MistakePatch) -> MistakeRead:
    row = session.exec(
        text("SELECT * FROM mistakes WHERE question_id = :question_id"),
        params={"question_id": question_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Mistake not found")
    if payload.note_md is not None:
        session.exec(
            text("UPDATE mistakes SET note_md = :note_md WHERE question_id = :question_id"),
            params={"note_md": payload.note_md, "question_id": question_id},
        )
    if payload.mastered is True:
        result = session.exec(
            text(
                """
                UPDATE mistakes
                SET mastered_at = :now, mastered_source = 'manual'
                WHERE question_id = :question_id AND mastered_at IS NULL
                """
            ),
            params={"now": utc_now(), "question_id": question_id},
        )
        if result.rowcount == 1:
            for node in nodes_for_question(session, question_id):
                apply_event(session, node, "master")
    if payload.mastered is False:
        session.exec(
            text(
                """
                UPDATE mistakes
                SET mastered_at = NULL, mastered_source = NULL
                WHERE question_id = :question_id
                """
            ),
            params={"question_id": question_id},
        )
    session.commit()
    return _mistake_read(session, question_id)


def add_diagnosis(session: Session, attempt_id: int, payload: DiagnosisInput) -> DiagnosisRead:
    get_attempt(session, attempt_id)
    diagnosis_id = _insert_diagnosis(session, attempt_id, payload)
    node = node_from_target(session, payload.target_type, payload.target_id, payload.custom_label)
    apply_event(session, node, "wrong")
    session.commit()
    return next(item for item in list_diagnoses(session, attempt_id) if item.id == diagnosis_id)


def list_diagnoses(session: Session, attempt_id: int) -> list[DiagnosisRead]:
    rows = session.exec(
        text(
            """
            SELECT d.*,
                   COALESCE(kp.title, p.name, s.name, cp.name, d.custom_label) AS title
            FROM mistake_diagnoses d
            LEFT JOIN knowledge_points kp ON kp.id = d.kp_id
            LEFT JOIN question_patterns p ON p.id = d.pattern_id
            LEFT JOIN skills s ON s.id = d.skill_id
            LEFT JOIN common_pitfalls cp ON cp.id = d.pitfall_id
            WHERE d.attempt_id = :attempt_id
            ORDER BY d.id
            """
        ),
        params={"attempt_id": attempt_id},
    ).all()
    return [
        DiagnosisRead(
            id=row.id,
            attempt_id=row.attempt_id,
            target_type=_diagnosis_type(row),
            target_id=row.kp_id or row.pattern_id or row.skill_id or row.pitfall_id,
            title=row.title,
            note_md=row.note_md,
            confidence=row.confidence,
            source=row.source,
            created_at=row.created_at,
        )
        for row in rows
    ]


def _mark_wrong(session: Session, question_id: int, attempt_id: int, attempted_at: str) -> None:
    exists = session.exec(
        text("SELECT question_id FROM mistakes WHERE question_id = :question_id"),
        params={"question_id": question_id},
    ).first()
    if exists:
        session.exec(
            text(
                """
                UPDATE mistakes
                SET last_wrong_at = :attempted_at,
                    wrong_count = wrong_count + 1,
                    last_attempt_id = :attempt_id,
                    mastered_streak = 0,
                    mastered_at = NULL,
                    mastered_source = NULL
                WHERE question_id = :question_id
                """
            ),
            params={"attempted_at": attempted_at, "attempt_id": attempt_id, "question_id": question_id},
        )
    else:
        session.exec(
            text(
                """
                INSERT INTO mistakes(question_id, first_wrong_at, last_wrong_at, wrong_count, last_attempt_id)
                VALUES (:question_id, :attempted_at, :attempted_at, 1, :attempt_id)
                """
            ),
            params={"question_id": question_id, "attempted_at": attempted_at, "attempt_id": attempt_id},
        )


def _mark_correct(session: Session, question_id: int, attempt_id: int) -> None:
    session.exec(
        text(
            """
            UPDATE mistakes
            SET mastered_streak = mastered_streak + 1,
                last_attempt_id = :attempt_id
            WHERE question_id = :question_id AND mastered_at IS NULL
            """
        ),
        params={"question_id": question_id, "attempt_id": attempt_id},
    )


def _rule_diagnoses(session: Session, question_id: int) -> list[DiagnosisInput]:
    return [
        DiagnosisInput(target_type=node.target_type, target_id=node.target_id, source="rule")
        for node in nodes_for_question(session, question_id)
    ]


def _insert_diagnosis(session: Session, attempt_id: int, payload: DiagnosisInput) -> int:
    target = _target_columns(payload)
    result = session.exec(
        text(
            """
            INSERT INTO mistake_diagnoses(
              attempt_id, kp_id, pattern_id, skill_id, pitfall_id, custom_label,
              note_md, confidence, source, created_at
            )
            VALUES (
              :attempt_id, :kp_id, :pattern_id, :skill_id, :pitfall_id, :custom_label,
              :note_md, :confidence, :source, :created_at
            )
            """
        ),
        params={
            "attempt_id": attempt_id,
            **target,
            "note_md": payload.note_md,
            "confidence": payload.confidence,
            "source": payload.source,
            "created_at": utc_now(),
        },
    )
    return int(result.lastrowid)


def _target_columns(payload: DiagnosisInput) -> dict[str, str | int | None]:
    target = {"kp_id": None, "pattern_id": None, "skill_id": None, "pitfall_id": None, "custom_label": None}
    if payload.target_type == "kp":
        target["kp_id"] = str(payload.target_id)
    elif payload.target_type == "pattern":
        target["pattern_id"] = int(payload.target_id)
    elif payload.target_type == "skill":
        target["skill_id"] = int(payload.target_id)
    elif payload.target_type == "pitfall":
        target["pitfall_id"] = int(payload.target_id)
    elif payload.target_type == "custom":
        target["custom_label"] = payload.custom_label or "自定义错因"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported diagnosis target: {payload.target_type}")
    return target


def _diagnosis_type(row) -> str:
    if row.kp_id is not None:
        return "kp"
    if row.pattern_id is not None:
        return "pattern"
    if row.skill_id is not None:
        return "skill"
    if row.pitfall_id is not None:
        return "pitfall"
    return "custom"


def _should_suggest_mastered(session: Session, question_id: int, mastered_at, mastered_streak: int) -> bool:
    """§16.4: suggest "mastered" only when the recent correct streak also spans
    at least SUGGEST_MASTERED_MIN_SPAN_HOURS, so a single sitting of rapid-fire
    correct answers does not trip the hint."""
    if mastered_at is not None or mastered_streak < SUGGEST_MASTERED_MIN_STREAK:
        return False
    rows = session.exec(
        text(
            """
            SELECT attempted_at FROM attempts
            WHERE question_id = :question_id AND is_correct = 1
            ORDER BY attempted_at DESC
            LIMIT :limit
            """
        ),
        params={"question_id": question_id, "limit": SUGGEST_MASTERED_MIN_STREAK},
    ).all()
    if len(rows) < SUGGEST_MASTERED_MIN_STREAK:
        return False
    times = [datetime.fromisoformat(row.attempted_at) for row in rows]
    return max(times) - min(times) >= timedelta(hours=SUGGEST_MASTERED_MIN_SPAN_HOURS)


def _mistake_read(session: Session, question_id: int) -> MistakeRead:
    row = session.exec(
        text("SELECT * FROM mistakes WHERE question_id = :question_id"),
        params={"question_id": question_id},
    ).one()
    diagnoses = list_diagnoses(session, row.last_attempt_id) if row.last_attempt_id else []
    return MistakeRead(
        question=get_question(session, question_id),
        first_wrong_at=row.first_wrong_at,
        last_wrong_at=row.last_wrong_at,
        wrong_count=row.wrong_count,
        last_attempt_id=row.last_attempt_id,
        note_md=row.note_md,
        mastered_at=row.mastered_at,
        mastered_source=row.mastered_source,
        mastered_streak=row.mastered_streak,
        suggest_mastered=_should_suggest_mastered(session, question_id, row.mastered_at, row.mastered_streak),
        diagnoses=diagnoses,
        weaknesses=_weaknesses_for_question(session, question_id),
    )


def weaknesses_for_question(session: Session, question_id: int) -> list[WeaknessRead]:
    """Public accessor for the personal-weakness nodes linked to a question."""
    return _weaknesses_for_question(session, question_id)


def _weaknesses_for_question(session: Session, question_id: int) -> list[WeaknessRead]:
    conditions = []
    params = {"question_id": question_id}
    for target_type, table, col in (
        ("kp", "question_kp", "kp_id"),
        ("pattern", "question_patterns_map", "pattern_id"),
        ("skill", "question_skills", "skill_id"),
        ("pitfall", "question_pitfalls", "pitfall_id"),
    ):
        conditions.append(
            f"""
            ({_target_column(target_type)} IN (
              SELECT {col} FROM {table} WHERE question_id = :question_id
            ))
            """
        )
    rows = session.exec(
        text(
            f"""
            SELECT * FROM personal_weaknesses
            WHERE {' OR '.join(conditions)}
            ORDER BY strength DESC, updated_at DESC
            """
        ),
        params=params,
    ).all()
    return [_weakness_read(row) for row in rows]


def _target_column(target_type: str) -> str:
    return {
        "kp": "kp_id",
        "pattern": "pattern_id",
        "skill": "skill_id",
        "pitfall": "pitfall_id",
    }[target_type]


def _weakness_read(row) -> WeaknessRead:
    target_type = "custom"
    target_id = None
    for candidate, attr in (("kp", "kp_id"), ("pattern", "pattern_id"), ("skill", "skill_id"), ("pitfall", "pitfall_id")):
        value = getattr(row, attr)
        if value is not None:
            target_type = candidate
            target_id = value
            break
    return WeaknessRead(
        id=row.id,
        target_type=target_type,
        target_id=target_id,
        title=row.title,
        strength=row.strength,
        mastery=row.mastery,
        evidence_count=row.evidence_count,
        last_seen_at=row.last_seen_at,
        updated_at=row.updated_at,
    )
