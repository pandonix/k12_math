from __future__ import annotations

import re
from typing import Any, Iterable

from fastapi import HTTPException
from sqlmodel import Session, text


MIN_PERSONAL_ATTEMPTS = 5
MIN_PERSONAL_MISTAKES = 3
MIN_PERSONAL_WEAKNESSES = 2

NODE_TYPES = {"weakness", "kp", "pattern", "skill", "pitfall"}


def sync_pattern_edges_from_question_edges(
    session: Session,
    pattern_ids: Iterable[int] | None = None,
) -> None:
    """Materialize pattern->skill/pitfall edges from linked questions.

    The learning-map page reads pattern-level edges. Imports and manual entry
    often attach skills/pitfalls only to questions, so this keeps the pattern
    layer useful without requiring a second manual tagging pass.
    """
    ids = sorted({int(pattern_id) for pattern_id in pattern_ids or []})
    where_sql, params = _pattern_filter(ids)
    if ids:
        placeholders = ", ".join(f":pattern_id_{index}" for index, _ in enumerate(ids))
        session.exec(
            text(f"DELETE FROM pattern_skills WHERE pattern_id IN ({placeholders})"),
            params=params,
        )
        session.exec(
            text(f"DELETE FROM pattern_pitfalls WHERE pattern_id IN ({placeholders})"),
            params=params,
        )
    elif pattern_ids is None:
        session.exec(text("DELETE FROM pattern_skills"))
        session.exec(text("DELETE FROM pattern_pitfalls"))
    session.exec(
        text(
            f"""
            INSERT INTO pattern_skills(pattern_id, skill_id, weight)
            SELECT qpm.pattern_id,
                   qs.skill_id,
                   MAX(COALESCE(qpm.weight, 1.0) * COALESCE(qs.weight, 1.0)) AS weight
            FROM question_patterns_map qpm
            JOIN question_skills qs ON qs.question_id = qpm.question_id
            {where_sql}
            GROUP BY qpm.pattern_id, qs.skill_id
            ON CONFLICT(pattern_id, skill_id) DO UPDATE SET
              weight = excluded.weight
            """
        ),
        params=params,
    )
    session.exec(
        text(
            f"""
            INSERT INTO pattern_pitfalls(pattern_id, pitfall_id, weight)
            SELECT qpm.pattern_id,
                   qp.pitfall_id,
                   MAX(COALESCE(qpm.weight, 1.0) * COALESCE(qp.weight, 1.0)) AS weight
            FROM question_patterns_map qpm
            JOIN question_pitfalls qp ON qp.question_id = qpm.question_id
            {where_sql}
            GROUP BY qpm.pattern_id, qp.pitfall_id
            ON CONFLICT(pattern_id, pitfall_id) DO UPDATE SET
              weight = excluded.weight
            """
        ),
        params=params,
    )


def learning_map_summary(session: Session) -> dict[str, Any]:
    counts = {
        "personal_weaknesses": _count(session, "personal_weaknesses"),
        "knowledge_points": _count(session, "knowledge_points"),
        "question_patterns": _count(session, "question_patterns"),
        "skills": _count(session, "skills"),
        "common_pitfalls": _count(session, "common_pitfalls"),
        "questions": _count(session, "questions"),
        "attempts": _count(session, "attempts"),
        "mistakes": _count(session, "mistakes"),
        "mistake_diagnoses": _count(session, "mistake_diagnoses"),
    }
    readiness = personal_readiness(session, counts)
    return {"counts": counts, "readiness": readiness}


def personal_readiness(
    session: Session,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    current = counts or {
        "attempts": _count(session, "attempts"),
        "mistakes": _count(session, "mistakes"),
        "personal_weaknesses": _count(session, "personal_weaknesses"),
    }
    enough = (
        current.get("attempts", 0) >= MIN_PERSONAL_ATTEMPTS
        and current.get("mistakes", 0) >= MIN_PERSONAL_MISTAKES
        and current.get("personal_weaknesses", 0) >= MIN_PERSONAL_WEAKNESSES
    )
    missing = {
        "attempts": max(0, MIN_PERSONAL_ATTEMPTS - current.get("attempts", 0)),
        "mistakes": max(0, MIN_PERSONAL_MISTAKES - current.get("mistakes", 0)),
        "personal_weaknesses": max(
            0,
            MIN_PERSONAL_WEAKNESSES - current.get("personal_weaknesses", 0),
        ),
    }
    return {
        "has_enough_personal_data": enough,
        "default_entry": "weakness" if enough else "kp",
        "thresholds": {
            "attempts": MIN_PERSONAL_ATTEMPTS,
            "mistakes": MIN_PERSONAL_MISTAKES,
            "personal_weaknesses": MIN_PERSONAL_WEAKNESSES,
        },
        "missing": missing,
        "message": (
            "个人证据已足够，可默认从薄弱点进入。"
            if enough
            else "个人练习证据不足，先从知识点或题型学习地图进入。"
        ),
    }


def list_learning_map_nodes(
    session: Session,
    node_type: str,
    *,
    q: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _validate_node_type(node_type)
    limit = max(1, min(limit, 200))
    like_sql = ""
    params: dict[str, Any] = {"limit": limit}
    if q:
        params["q"] = f"%{q.strip()}%"

    if node_type == "weakness":
        like_sql = "AND title LIKE :q" if q else ""
        rows = session.exec(
            text(
                f"""
                SELECT id, title AS name,
                       evidence_count, strength, mastery, updated_at
                FROM personal_weaknesses
                WHERE 1 = 1 {like_sql}
                ORDER BY strength * CASE WHEN evidence_count > 0 THEN evidence_count ELSE 1 END DESC,
                         updated_at DESC
                LIMIT :limit
                """
            ),
            params=params,
        ).all()
        return [
            _node_list_item(
                "weakness",
                row.id,
                row.name,
                evidence_count=row.evidence_count,
                strength=row.strength,
                mastery=row.mastery,
            )
            for row in rows
        ]

    if node_type == "kp":
        like_sql = (
            "AND (kp.title LIKE :q OR kp.chapter LIKE :q OR kp.book LIKE :q)"
            if q
            else ""
        )
        rows = session.exec(
            text(
                f"""
                SELECT kp.id,
                       kp.title AS name,
                       kp.book,
                       kp.chapter,
                       kp.section,
                       COUNT(DISTINCT qk.question_id) AS question_count
                FROM knowledge_points kp
                LEFT JOIN question_kp qk ON qk.kp_id = kp.id
                WHERE 1 = 1 {like_sql}
                GROUP BY kp.id
                ORDER BY kp.order_index
                LIMIT :limit
                """
            ),
            params=params,
        ).all()
        return [
            _node_list_item(
                "kp",
                row.id,
                row.name,
                group_label=row.chapter or row.book,
                question_count=row.question_count,
            )
            for row in rows
        ]

    table, title_col = _node_table(node_type)
    question_edge, question_key = _question_edge(node_type)
    pattern_join = _pattern_count_join(node_type)
    like_sql = f"AND node.{title_col} LIKE :q" if q else ""
    rows = session.exec(
        text(
            f"""
            SELECT node.id,
                   node.{title_col} AS name,
                   node.{title_col} AS search_text,
                   COUNT(DISTINCT qe.question_id) AS question_count,
                   {pattern_join["select"]} AS pattern_count
            FROM {table} node
            LEFT JOIN {question_edge} qe ON qe.{question_key} = node.id
            {pattern_join["join"]}
            WHERE 1 = 1 {like_sql}
            GROUP BY node.id
            ORDER BY question_count DESC, node.id
            LIMIT :limit
            """
        ),
        params=params,
    ).all()
    return [
        _node_list_item(
            node_type,
            row.id,
            row.name,
            question_count=row.question_count,
            pattern_count=row.pattern_count,
        )
        for row in rows
    ]


def learning_map_node_detail(
    session: Session,
    node_type: str,
    node_id: str,
) -> dict[str, Any]:
    _validate_node_type(node_type)
    if node_type == "weakness":
        row = session.exec(
            text("SELECT * FROM personal_weaknesses WHERE id = :id"),
            params={"id": int(node_id)},
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="Weakness not found")
        target_type, target_id = _weakness_target(row)
        questions = _questions_for_target(session, target_type, target_id, limit=8)
        return {
            "node": _node_list_item(
                "weakness",
                row.id,
                row.title,
                evidence_count=row.evidence_count,
                strength=row.strength,
                mastery=row.mastery,
            ),
            "related": _related_for_target(session, target_type, target_id),
            "weaknesses": [_weakness_dict(row)],
            "questions": questions,
            "recommendations": questions[:5],
            "readiness": personal_readiness(session),
        }

    typed_id: str | int = node_id if node_type == "kp" else int(node_id)
    node = _load_node(session, node_type, typed_id)
    if not node:
        raise HTTPException(status_code=404, detail="Learning map node not found")

    questions = _questions_for_target(session, node_type, typed_id, limit=8)
    return {
        "node": node,
        "related": _related_for_target(session, node_type, typed_id),
        "weaknesses": _weaknesses_for_target(session, node_type, typed_id),
        "questions": questions,
        "recommendations": questions[:5],
        "readiness": personal_readiness(session),
    }


def _pattern_filter(pattern_ids: Iterable[int] | None) -> tuple[str, dict[str, int]]:
    ids = sorted({int(pattern_id) for pattern_id in pattern_ids or []})
    if not ids:
        return "", {}
    params = {f"pattern_id_{index}": pattern_id for index, pattern_id in enumerate(ids)}
    placeholders = ", ".join(f":{name}" for name in params)
    return f"WHERE qpm.pattern_id IN ({placeholders})", params


def _count(session: Session, table: str) -> int:
    return int(session.exec(text(f"SELECT COUNT(*) AS count FROM {table}")).one().count or 0)


def _validate_node_type(node_type: str) -> None:
    if node_type not in NODE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported learning map node type")


def _node_table(node_type: str) -> tuple[str, str]:
    if node_type == "pattern":
        return ("question_patterns", "name")
    if node_type == "skill":
        return ("skills", "name")
    if node_type == "pitfall":
        return ("common_pitfalls", "name")
    raise ValueError(node_type)


def _question_edge(node_type: str) -> tuple[str, str]:
    if node_type == "kp":
        return ("question_kp", "kp_id")
    if node_type == "pattern":
        return ("question_patterns_map", "pattern_id")
    if node_type == "skill":
        return ("question_skills", "skill_id")
    if node_type == "pitfall":
        return ("question_pitfalls", "pitfall_id")
    raise ValueError(node_type)


def _pattern_count_join(node_type: str) -> dict[str, str]:
    if node_type == "pattern":
        return {"select": "1", "join": ""}
    if node_type == "skill":
        return {
            "select": "COUNT(DISTINCT pe.pattern_id)",
            "join": "LEFT JOIN pattern_skills pe ON pe.skill_id = node.id",
        }
    if node_type == "pitfall":
        return {
            "select": "COUNT(DISTINCT pe.pattern_id)",
            "join": "LEFT JOIN pattern_pitfalls pe ON pe.pitfall_id = node.id",
        }
    raise ValueError(node_type)


def _node_list_item(
    node_type: str,
    node_id: str | int,
    name: str,
    **extra: Any,
) -> dict[str, Any]:
    clean_name = clean_node_name(node_type, name)
    return {
        "type": node_type,
        "id": node_id,
        "name": name,
        "display_name": clean_name,
        **extra,
    }


def clean_node_name(node_type: str, name: str) -> str:
    value = str(name or "").strip()
    if node_type == "pattern":
        value = re.sub(r"^题型[一二三四五六七八九十百\d]+\s*", "", value).strip()
    if node_type == "skill":
        value = re.sub(r"^方法技巧\s*\d+\s*", "", value).strip()
    if node_type == "pitfall":
        value = re.sub(r"^易混易错\s*\d+\s*", "", value).strip()
    return value or str(name or "").strip()


def _load_node(session: Session, node_type: str, node_id: str | int) -> dict[str, Any] | None:
    if node_type == "kp":
        row = session.exec(
            text(
                """
                SELECT id, title AS name, book, chapter, section, content_md
                FROM knowledge_points
                WHERE id = :id
                """
            ),
            params={"id": node_id},
        ).first()
        if not row:
            return None
        return _node_list_item(
            "kp",
            row.id,
            row.name,
            group_label=row.chapter or row.book,
            content_md=row.content_md,
        )

    table, title_col = _node_table(node_type)
    row = session.exec(
        text(f"SELECT * FROM {table} WHERE id = :id"),
        params={"id": node_id},
    ).first()
    if not row:
        return None
    return _node_list_item(
        node_type,
        row.id,
        getattr(row, title_col),
        content_md=getattr(row, "content_md", None),
        strategy_md=getattr(row, "strategy_md", None),
        source=getattr(row, "source", None),
    )


def _related_for_target(
    session: Session,
    target_type: str,
    target_id: str | int | None,
) -> dict[str, list[dict[str, Any]]]:
    empty = {"knowledge_points": [], "patterns": [], "skills": [], "pitfalls": []}
    if target_id is None:
        return empty
    if target_type == "kp":
        empty["patterns"] = _patterns_for_kp(session, str(target_id))
        empty["skills"] = _skills_for_kp(session, str(target_id))
        empty["pitfalls"] = _pitfalls_for_kp(session, str(target_id))
        return empty
    if target_type == "pattern":
        empty["knowledge_points"] = _kps_for_pattern(session, int(target_id))
        empty["skills"] = _skills_for_pattern(session, int(target_id))
        empty["pitfalls"] = _pitfalls_for_pattern(session, int(target_id))
        return empty
    if target_type == "skill":
        empty["knowledge_points"] = _kps_for_question_node(session, "skill", int(target_id))
        empty["patterns"] = _patterns_for_question_node(session, "skill", int(target_id))
        empty["pitfalls"] = _co_nodes_for_question_node(session, "skill", int(target_id), "pitfall")
        return empty
    if target_type == "pitfall":
        empty["knowledge_points"] = _kps_for_question_node(session, "pitfall", int(target_id))
        empty["patterns"] = _patterns_for_question_node(session, "pitfall", int(target_id))
        empty["skills"] = _co_nodes_for_question_node(session, "pitfall", int(target_id), "skill")
        return empty
    return empty


def _kps_for_pattern(session: Session, pattern_id: int) -> list[dict[str, Any]]:
    return [
        _node_list_item("kp", row.id, row.title, group_label=row.chapter or row.book)
        for row in session.exec(
            text(
                """
                SELECT kp.id, kp.title, kp.book, kp.chapter
                FROM knowledge_points kp
                JOIN pattern_kp pk ON pk.kp_id = kp.id
                WHERE pk.pattern_id = :pattern_id
                ORDER BY pk.weight DESC, kp.order_index
                """
            ),
            params={"pattern_id": pattern_id},
        ).all()
    ]


def _patterns_for_kp(session: Session, kp_id: str) -> list[dict[str, Any]]:
    return [
        _node_list_item("pattern", row.id, row.name, question_count=row.question_count)
        for row in session.exec(
            text(
                """
                SELECT p.id, p.name, COUNT(DISTINCT qpm.question_id) AS question_count
                FROM question_patterns p
                JOIN question_patterns_map qpm ON qpm.pattern_id = p.id
                JOIN question_kp qk ON qk.question_id = qpm.question_id
                WHERE qk.kp_id = :kp_id
                GROUP BY p.id
                ORDER BY question_count DESC, p.id
                LIMIT 30
                """
            ),
            params={"kp_id": kp_id},
        ).all()
    ]


def _skills_for_pattern(session: Session, pattern_id: int) -> list[dict[str, Any]]:
    return _pattern_nodes(session, pattern_id, "skill")


def _pitfalls_for_pattern(session: Session, pattern_id: int) -> list[dict[str, Any]]:
    return _pattern_nodes(session, pattern_id, "pitfall")


def _pattern_nodes(session: Session, pattern_id: int, node_type: str) -> list[dict[str, Any]]:
    table, title_col = _node_table(node_type)
    edge_table = "pattern_skills" if node_type == "skill" else "pattern_pitfalls"
    edge_key = "skill_id" if node_type == "skill" else "pitfall_id"
    return [
        _node_list_item(node_type, row.id, getattr(row, title_col), weight=row.weight)
        for row in session.exec(
            text(
                f"""
                SELECT node.id, node.{title_col}, edge.weight
                FROM {table} node
                JOIN {edge_table} edge ON edge.{edge_key} = node.id
                WHERE edge.pattern_id = :pattern_id
                ORDER BY edge.weight DESC, node.id
                LIMIT 30
                """
            ),
            params={"pattern_id": pattern_id},
        ).all()
    ]


def _skills_for_kp(session: Session, kp_id: str) -> list[dict[str, Any]]:
    return _question_nodes_for_kp(session, kp_id, "skill")


def _pitfalls_for_kp(session: Session, kp_id: str) -> list[dict[str, Any]]:
    return _question_nodes_for_kp(session, kp_id, "pitfall")


def _question_nodes_for_kp(session: Session, kp_id: str, node_type: str) -> list[dict[str, Any]]:
    table, title_col = _node_table(node_type)
    edge_table, edge_key = _question_edge(node_type)
    return [
        _node_list_item(node_type, row.id, getattr(row, title_col), question_count=row.question_count)
        for row in session.exec(
            text(
                f"""
                SELECT node.id, node.{title_col}, COUNT(DISTINCT edge.question_id) AS question_count
                FROM {table} node
                JOIN {edge_table} edge ON edge.{edge_key} = node.id
                JOIN question_kp qk ON qk.question_id = edge.question_id
                WHERE qk.kp_id = :kp_id
                GROUP BY node.id
                ORDER BY question_count DESC, node.id
                LIMIT 30
                """
            ),
            params={"kp_id": kp_id},
        ).all()
    ]


def _kps_for_question_node(session: Session, node_type: str, node_id: int) -> list[dict[str, Any]]:
    edge_table, edge_key = _question_edge(node_type)
    return [
        _node_list_item("kp", row.id, row.title, group_label=row.chapter or row.book)
        for row in session.exec(
            text(
                f"""
                SELECT kp.id, kp.title, kp.book, kp.chapter, COUNT(DISTINCT qk.question_id) AS question_count
                FROM knowledge_points kp
                JOIN question_kp qk ON qk.kp_id = kp.id
                JOIN {edge_table} edge ON edge.question_id = qk.question_id
                WHERE edge.{edge_key} = :node_id
                GROUP BY kp.id
                ORDER BY question_count DESC, kp.order_index
                LIMIT 30
                """
            ),
            params={"node_id": node_id},
        ).all()
    ]


def _patterns_for_question_node(session: Session, node_type: str, node_id: int) -> list[dict[str, Any]]:
    edge_table, edge_key = _question_edge(node_type)
    pattern_edge = "pattern_skills" if node_type == "skill" else "pattern_pitfalls"
    pattern_key = "skill_id" if node_type == "skill" else "pitfall_id"
    return [
        _node_list_item("pattern", row.id, row.name, question_count=row.question_count)
        for row in session.exec(
            text(
                f"""
                SELECT p.id, p.name, COUNT(DISTINCT qpm.question_id) AS question_count
                FROM question_patterns p
                LEFT JOIN {pattern_edge} pe ON pe.pattern_id = p.id
                LEFT JOIN question_patterns_map qpm ON qpm.pattern_id = p.id
                LEFT JOIN {edge_table} edge ON edge.question_id = qpm.question_id
                WHERE pe.{pattern_key} = :node_id OR edge.{edge_key} = :node_id
                GROUP BY p.id
                ORDER BY question_count DESC, p.id
                LIMIT 30
                """
            ),
            params={"node_id": node_id},
        ).all()
    ]


def _co_nodes_for_question_node(
    session: Session,
    source_type: str,
    source_id: int,
    target_type: str,
) -> list[dict[str, Any]]:
    source_table, source_key = _question_edge(source_type)
    target_table, target_key = _question_edge(target_type)
    node_table, title_col = _node_table(target_type)
    return [
        _node_list_item(target_type, row.id, getattr(row, title_col), question_count=row.question_count)
        for row in session.exec(
            text(
                f"""
                SELECT node.id, node.{title_col}, COUNT(DISTINCT target.question_id) AS question_count
                FROM {node_table} node
                JOIN {target_table} target ON target.{target_key} = node.id
                JOIN {source_table} source ON source.question_id = target.question_id
                WHERE source.{source_key} = :source_id
                GROUP BY node.id
                ORDER BY question_count DESC, node.id
                LIMIT 30
                """
            ),
            params={"source_id": source_id},
        ).all()
    ]


def _questions_for_target(
    session: Session,
    target_type: str,
    target_id: str | int | None,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if target_id is None or target_type == "custom":
        return []
    edge_table, edge_key = _question_edge(target_type)
    rows = session.exec(
        text(
            f"""
            SELECT q.id, q.source, q.difficulty, q.stem_md, q.updated_at
            FROM questions q
            JOIN {edge_table} edge ON edge.question_id = q.id
            WHERE edge.{edge_key} = :target_id
            ORDER BY q.updated_at DESC, q.id DESC
            LIMIT :limit
            """
        ),
        params={"target_id": target_id, "limit": max(1, min(limit, 30))},
    ).all()
    return [dict(row._mapping) for row in rows]


def _weaknesses_for_target(
    session: Session,
    target_type: str,
    target_id: str | int | None,
) -> list[dict[str, Any]]:
    if target_id is None:
        return []
    column = {
        "kp": "kp_id",
        "pattern": "pattern_id",
        "skill": "skill_id",
        "pitfall": "pitfall_id",
    }.get(target_type)
    if not column:
        return []
    return [
        _weakness_dict(row)
        for row in session.exec(
            text(f"SELECT * FROM personal_weaknesses WHERE {column} = :target_id"),
            params={"target_id": target_id},
        ).all()
    ]


def _weakness_target(row) -> tuple[str, str | int | None]:
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


def _weakness_dict(row) -> dict[str, Any]:
    target_type, target_id = _weakness_target(row)
    return {
        "id": row.id,
        "type": "weakness",
        "target_type": target_type,
        "target_id": target_id,
        "title": row.title,
        "strength": float(row.strength or 0),
        "mastery": float(row.mastery or 0),
        "evidence_count": int(row.evidence_count or 0),
        "last_seen_at": row.last_seen_at,
        "updated_at": row.updated_at,
    }
