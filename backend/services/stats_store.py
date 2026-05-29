from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, text

from backend.schemas import (
    QuestionRead,
    StatsEvidenceItem,
    StatsKpHeatmapItem,
    StatsTrendPoint,
    StatsTypeRadarItem,
    StatsWeaknessDetail,
    StatsWeaknessItem,
)
from backend.services.question_store import get_question


def weak_top(session: Session, limit: int = 10) -> list[StatsWeaknessItem]:
    rows = session.exec(
        text(
            """
            SELECT *
            FROM personal_weaknesses
            ORDER BY
              strength * CASE WHEN evidence_count > 0 THEN evidence_count ELSE 1 END DESC,
              last_seen_at DESC,
              updated_at DESC
            LIMIT :limit
            """
        ),
        params={"limit": max(1, min(limit, 50))},
    ).all()
    return [_weakness_item(session, row) for row in rows]


def heatmap(session: Session) -> list[StatsKpHeatmapItem]:
    rows = session.exec(
        text(
            """
            SELECT kp.id AS kp_id,
                   kp.title,
                   kp.book,
                   kp.chapter,
                   kp.section,
                   COALESCE(pw.strength, 0) AS strength,
                   COALESCE(pw.mastery, 0) AS mastery,
                   COALESCE(pw.evidence_count, 0) AS evidence_count,
                   COALESCE(q.question_count, 0) AS question_count,
                   COALESCE(w.wrong_count, 0) AS wrong_count
            FROM knowledge_points kp
            LEFT JOIN personal_weaknesses pw ON pw.kp_id = kp.id
            LEFT JOIN (
              SELECT kp_id, COUNT(DISTINCT question_id) AS question_count
              FROM question_kp
              GROUP BY kp_id
            ) q ON q.kp_id = kp.id
            LEFT JOIN (
              SELECT qkp.kp_id, COUNT(*) AS wrong_count
              FROM question_kp qkp
              JOIN attempts a ON a.question_id = qkp.question_id
              WHERE a.is_correct = 0
              GROUP BY qkp.kp_id
            ) w ON w.kp_id = kp.id
            WHERE COALESCE(pw.evidence_count, 0) > 0 OR COALESCE(w.wrong_count, 0) > 0
            ORDER BY
              COALESCE(pw.strength, 0) * CASE WHEN COALESCE(pw.evidence_count, 0) > 0 THEN pw.evidence_count ELSE 1 END DESC,
              w.wrong_count DESC,
              kp.order_index
            """
        )
    ).all()
    return [
        StatsKpHeatmapItem(
            kp_id=row.kp_id,
            title=row.title,
            book=row.book,
            chapter=row.chapter,
            section=row.section,
            strength=float(row.strength or 0),
            mastery=float(row.mastery or 0),
            evidence_count=int(row.evidence_count or 0),
            wrong_count=int(row.wrong_count or 0),
            question_count=int(row.question_count or 0),
        )
        for row in rows
    ]


def type_radar(session: Session, limit: int = 12) -> list[StatsTypeRadarItem]:
    rows = session.exec(
        text(
            """
            SELECT p.id AS pattern_id,
                   p.name,
                   COALESCE(pw.strength, 0) AS strength,
                   COALESCE(pw.mastery, 0) AS mastery,
                   COALESCE(pw.evidence_count, 0) AS evidence_count,
                   COALESCE(q.question_count, 0) AS question_count,
                   COALESCE(w.wrong_count, 0) AS wrong_count
            FROM question_patterns p
            LEFT JOIN personal_weaknesses pw ON pw.pattern_id = p.id
            LEFT JOIN (
              SELECT pattern_id, COUNT(DISTINCT question_id) AS question_count
              FROM question_patterns_map
              GROUP BY pattern_id
            ) q ON q.pattern_id = p.id
            LEFT JOIN (
              SELECT qpm.pattern_id, COUNT(*) AS wrong_count
              FROM question_patterns_map qpm
              JOIN attempts a ON a.question_id = qpm.question_id
              WHERE a.is_correct = 0
              GROUP BY qpm.pattern_id
            ) w ON w.pattern_id = p.id
            WHERE COALESCE(pw.evidence_count, 0) > 0 OR COALESCE(w.wrong_count, 0) > 0
            ORDER BY
              COALESCE(pw.strength, 0) * CASE WHEN COALESCE(pw.evidence_count, 0) > 0 THEN pw.evidence_count ELSE 1 END DESC,
              w.wrong_count DESC,
              p.id
            LIMIT :limit
            """
        ),
        params={"limit": max(1, min(limit, 30))},
    ).all()
    return [
        StatsTypeRadarItem(
            pattern_id=row.pattern_id,
            name=row.name,
            strength=float(row.strength or 0),
            mastery=float(row.mastery or 0),
            evidence_count=int(row.evidence_count or 0),
            wrong_count=int(row.wrong_count or 0),
            question_count=int(row.question_count or 0),
        )
        for row in rows
    ]


def personal_pitfalls(session: Session, limit: int = 10) -> list[StatsWeaknessItem]:
    rows = session.exec(
        text(
            """
            SELECT *
            FROM personal_weaknesses
            WHERE pitfall_id IS NOT NULL OR custom_label IS NOT NULL
            ORDER BY
              strength * CASE WHEN evidence_count > 0 THEN evidence_count ELSE 1 END DESC,
              last_seen_at DESC,
              updated_at DESC
            LIMIT :limit
            """
        ),
        params={"limit": max(1, min(limit, 50))},
    ).all()
    return [_weakness_item(session, row) for row in rows]


def trend(session: Session, period: str = "week") -> list[StatsTrendPoint]:
    days_by_period = {"week": 7, "month": 30, "quarter": 90}
    days = days_by_period.get(period)
    params: dict[str, Any] = {}
    where = ""
    if days:
        start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date().isoformat()
        where = "WHERE date(a.attempted_at) >= :start"
        params["start"] = start
    rows = session.exec(
        text(
            f"""
            SELECT date(a.attempted_at) AS day,
                   COUNT(DISTINCT a.id) AS attempt_count,
                   COUNT(DISTINCT CASE WHEN a.is_correct = 0 THEN a.id END) AS wrong_count,
                   COUNT(DISTINCT CASE WHEN a.is_correct = 1 THEN a.id END) AS correct_count,
                   COUNT(d.id) AS diagnosis_count
            FROM attempts a
            LEFT JOIN mistake_diagnoses d ON d.attempt_id = a.id
            {where}
            GROUP BY day
            ORDER BY day
            """
        ),
        params=params,
    ).all()
    by_day = {
        row.day: StatsTrendPoint(
            date=row.day,
            attempt_count=int(row.attempt_count or 0),
            wrong_count=int(row.wrong_count or 0),
            correct_count=int(row.correct_count or 0),
            diagnosis_count=int(row.diagnosis_count or 0),
        )
        for row in rows
    }
    if not days:
        return list(by_day.values())
    start_date = datetime.fromisoformat(params["start"]).date()
    return [
        by_day.get(
            (start_date + timedelta(days=offset)).isoformat(),
            StatsTrendPoint(
                date=(start_date + timedelta(days=offset)).isoformat(),
                attempt_count=0,
                wrong_count=0,
                correct_count=0,
                diagnosis_count=0,
            ),
        )
        for offset in range(days)
    ]


def weakness_detail(session: Session, weakness_id: int) -> StatsWeaknessDetail:
    row = session.exec(
        text("SELECT * FROM personal_weaknesses WHERE id = :weakness_id"),
        params={"weakness_id": weakness_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Weakness not found")
    weakness = _weakness_item(session, row)
    evidence = _evidence(session, row)
    related_questions = _related_questions(session, row, evidence)
    return StatsWeaknessDetail(
        weakness=weakness,
        evidence=evidence,
        related_questions=related_questions,
        suggested_target={
            "mode": "weakness",
            "target_type": weakness.target_type,
            "target_id": weakness.target_id,
            "title": weakness.title,
        },
    )


def _weakness_item(session: Session, row) -> StatsWeaknessItem:
    target_type, target_id = _target(row)
    evidence_count = int(row.evidence_count or 0)
    strength = float(row.strength or 0)
    mastery = float(row.mastery or 0)
    return StatsWeaknessItem(
        id=row.id,
        target_type=target_type,
        target_id=target_id,
        title=row.title,
        strength=strength,
        mastery=mastery,
        evidence_count=evidence_count,
        last_seen_at=row.last_seen_at,
        updated_at=row.updated_at,
        score=round(strength * max(evidence_count, 1) * (1 - mastery * 0.35), 4),
        question_count=_question_count(session, target_type, target_id),
    )


def _target(row) -> tuple[str, str | int | None]:
    for target_type, attr in (
        ("kp", "kp_id"),
        ("pattern", "pattern_id"),
        ("skill", "skill_id"),
        ("pitfall", "pitfall_id"),
    ):
        value = getattr(row, attr)
        if value is not None:
            return target_type, value
    return "custom", None


def _question_count(session: Session, target_type: str, target_id: str | int | None) -> int:
    target = _edge_target(target_type, target_id)
    if not target:
        return 0
    table, column, value = target
    return int(
        session.exec(
            text(f"SELECT COUNT(DISTINCT question_id) AS count FROM {table} WHERE {column} = :value"),
            params={"value": value},
        ).one().count
        or 0
    )


def _edge_target(target_type: str, target_id: str | int | None) -> tuple[str, str, str | int] | None:
    if target_type == "kp" and target_id is not None:
        return ("question_kp", "kp_id", str(target_id))
    if target_type == "pattern" and target_id is not None:
        return ("question_patterns_map", "pattern_id", int(target_id))
    if target_type == "skill" and target_id is not None:
        return ("question_skills", "skill_id", int(target_id))
    if target_type == "pitfall" and target_id is not None:
        return ("question_pitfalls", "pitfall_id", int(target_id))
    return None


def _diagnosis_where(row) -> tuple[str, dict[str, Any]]:
    if row.kp_id is not None:
        return "d.kp_id = :target_id", {"target_id": row.kp_id}
    if row.pattern_id is not None:
        return "d.pattern_id = :target_id", {"target_id": row.pattern_id}
    if row.skill_id is not None:
        return "d.skill_id = :target_id", {"target_id": row.skill_id}
    if row.pitfall_id is not None:
        return "d.pitfall_id = :target_id", {"target_id": row.pitfall_id}
    return "d.custom_label = :target_id", {"target_id": row.custom_label}


def _evidence(session: Session, row) -> list[StatsEvidenceItem]:
    where_sql, params = _diagnosis_where(row)
    rows = session.exec(
        text(
            f"""
            SELECT d.id AS diagnosis_id,
                   d.note_md,
                   d.confidence,
                   d.source,
                   a.id AS attempt_id,
                   a.question_id,
                   a.attempted_at,
                   a.user_answer_md,
                   a.answer_image_path
            FROM mistake_diagnoses d
            JOIN attempts a ON a.id = d.attempt_id
            WHERE {where_sql}
            ORDER BY a.attempted_at DESC, d.id DESC
            LIMIT 12
            """
        ),
        params=params,
    ).all()
    items: list[StatsEvidenceItem] = []
    for row_item in rows:
        try:
            question = get_question(session, row_item.question_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        items.append(
            StatsEvidenceItem(
                attempt_id=row_item.attempt_id,
                question=question,
                attempted_at=row_item.attempted_at,
                user_answer_md=row_item.user_answer_md,
                answer_image_path=row_item.answer_image_path,
                note_md=row_item.note_md,
                confidence=float(row_item.confidence or 0),
                source=row_item.source,
            )
        )
    return items


def _related_questions(
    session: Session,
    row,
    evidence: list[StatsEvidenceItem],
) -> list[QuestionRead]:
    target_type, target_id = _target(row)
    target = _edge_target(target_type, target_id)
    if target:
        table, column, value = target
        rows = session.exec(
            text(
                f"""
                SELECT question_id
                FROM {table}
                WHERE {column} = :value
                ORDER BY question_id DESC
                LIMIT 8
                """
            ),
            params={"value": value},
        ).all()
        question_ids = [int(item.question_id) for item in rows]
    else:
        question_ids = [item.question.id for item in evidence]

    seen: set[int] = set()
    questions: list[QuestionRead] = []
    for question_id in question_ids:
        if question_id in seen:
            continue
        seen.add(question_id)
        try:
            questions.append(get_question(session, question_id))
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
    return questions
