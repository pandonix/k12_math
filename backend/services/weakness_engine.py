from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, text

from backend.services.question_store import utc_now


NODE_WEIGHT = {
    "kp": 0.3,
    "pattern": 0.5,
    "skill": 0.6,
    "pitfall": 0.8,
}

EVENT_DELTA = {
    "wrong": (1.0, -0.3),
    "correct": (-0.5, 0.2),
    "master": (-0.8, 0.4),
}


@dataclass(frozen=True)
class WeaknessNode:
    target_type: str
    target_id: str | int | None
    title: str


def apply_event(session: Session, node: WeaknessNode, event_type: str) -> None:
    if node.target_type == "custom":
        _upsert_custom(session, node)
        return
    weight = NODE_WEIGHT[node.target_type]
    strength_factor, mastery_factor = EVENT_DELTA[event_type]
    strength_delta = strength_factor * weight
    mastery_delta = mastery_factor * weight
    now = utc_now()

    column = _target_column(node.target_type)
    existing = session.exec(
        text(f"SELECT id FROM personal_weaknesses WHERE {column} = :target_id"),
        params={"target_id": node.target_id},
    ).first()
    if existing:
        session.exec(
            text(
                f"""
                UPDATE personal_weaknesses
                SET title = :title,
                    strength = MIN(1, MAX(0, strength + :strength_delta)),
                    mastery = MIN(1, MAX(0, mastery + :mastery_delta)),
                    evidence_count = evidence_count + 1,
                    last_seen_at = :now,
                    updated_at = :now
                WHERE {column} = :target_id
                """
            ),
            params={
                "title": node.title,
                "strength_delta": strength_delta,
                "mastery_delta": mastery_delta,
                "now": now,
                "target_id": node.target_id,
            },
        )
        return

    session.exec(
        text(
            f"""
            INSERT INTO personal_weaknesses(
              {column}, title, strength, mastery, evidence_count, last_seen_at, updated_at
            )
            VALUES (
              :target_id, :title,
              MIN(1, MAX(0, :strength_delta)),
              MIN(1, MAX(0, :mastery_delta)),
              1, :now, :now
            )
            """
        ),
        params={
            "target_id": node.target_id,
            "title": node.title,
            "strength_delta": strength_delta,
            "mastery_delta": mastery_delta,
            "now": now,
        },
    )


def nodes_for_question(session: Session, question_id: int) -> list[WeaknessNode]:
    nodes: list[WeaknessNode] = []
    nodes.extend(
        WeaknessNode("kp", row.id, row.title)
        for row in session.exec(
            text(
                """
                SELECT kp.id, kp.title
                FROM knowledge_points kp
                JOIN question_kp qk ON qk.kp_id = kp.id
                WHERE qk.question_id = :question_id
                ORDER BY qk.is_primary DESC, qk.weight DESC, kp.order_index
                """
            ),
            params={"question_id": question_id},
        ).all()
    )
    nodes.extend(
        WeaknessNode("pattern", row.id, row.name)
        for row in session.exec(
            text(
                """
                SELECT p.id, p.name
                FROM question_patterns p
                JOIN question_patterns_map qpm ON qpm.pattern_id = p.id
                WHERE qpm.question_id = :question_id
                ORDER BY qpm.is_primary DESC, qpm.weight DESC, p.id
                """
            ),
            params={"question_id": question_id},
        ).all()
    )
    nodes.extend(
        WeaknessNode("skill", row.id, row.name)
        for row in session.exec(
            text(
                """
                SELECT s.id, s.name
                FROM skills s
                JOIN question_skills qs ON qs.skill_id = s.id
                WHERE qs.question_id = :question_id
                ORDER BY qs.weight DESC, s.id
                """
            ),
            params={"question_id": question_id},
        ).all()
    )
    nodes.extend(
        WeaknessNode("pitfall", row.id, row.name)
        for row in session.exec(
            text(
                """
                SELECT p.id, p.name
                FROM common_pitfalls p
                JOIN question_pitfalls qp ON qp.pitfall_id = p.id
                WHERE qp.question_id = :question_id
                ORDER BY qp.weight DESC, p.id
                """
            ),
            params={"question_id": question_id},
        ).all()
    )
    return nodes


def node_from_target(session: Session, target_type: str, target_id: str | int | None, custom_label: str | None = None) -> WeaknessNode:
    if target_type == "custom":
        return WeaknessNode("custom", None, custom_label or "自定义错因")
    table, title_col = {
        "kp": ("knowledge_points", "title"),
        "pattern": ("question_patterns", "name"),
        "skill": ("skills", "name"),
        "pitfall": ("common_pitfalls", "name"),
    }[target_type]
    row = session.exec(
        text(f"SELECT id, {title_col} AS title FROM {table} WHERE id = :target_id"),
        params={"target_id": target_id},
    ).first()
    if not row:
        raise ValueError(f"Unknown {target_type} target: {target_id}")
    return WeaknessNode(target_type, row.id, row.title)


def _target_column(target_type: str) -> str:
    return {
        "kp": "kp_id",
        "pattern": "pattern_id",
        "skill": "skill_id",
        "pitfall": "pitfall_id",
    }[target_type]


def _upsert_custom(session: Session, node: WeaknessNode) -> None:
    now = utc_now()
    session.exec(
        text(
            """
            INSERT INTO personal_weaknesses(custom_label, title, strength, mastery, evidence_count, last_seen_at, updated_at)
            VALUES (:label, :title, 0, 0, 1, :now, :now)
            ON CONFLICT(custom_label) DO UPDATE SET
              evidence_count = evidence_count + 1,
              last_seen_at = excluded.last_seen_at,
              updated_at = excluded.updated_at
            """
        ),
        params={"label": node.title, "title": node.title, "now": now},
    )
