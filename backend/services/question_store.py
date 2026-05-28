from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, text

from backend.models import KnowledgePoint, Question
from backend.routers.kp import _summary
from backend.schemas import (
    GraphNode,
    NamedNodeInput,
    QuestionCreate,
    QuestionListResponse,
    QuestionRead,
    QuestionUpdate,
    WeightedKpInput,
)


def stem_hash(stem_md: str) -> str:
    return hashlib.sha256(stem_md.strip().encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def _split_names(value: str) -> list[NamedNodeInput]:
    names = [part.strip() for part in value.replace("，", ",").split(",")]
    return [NamedNodeInput(name=name) for name in names if name]


def _upsert_pattern(session: Session, node: NamedNodeInput, source: str | None = None) -> int:
    existing = session.exec(
        text("SELECT id FROM question_patterns WHERE name = :name ORDER BY id LIMIT 1"),
        params={"name": node.name},
    ).first()
    if existing:
        return int(existing.id)

    now = utc_now()
    result = session.exec(
        text(
            """
            INSERT INTO question_patterns(name, strategy_md, source, order_index, created_at, updated_at)
            VALUES (:name, :strategy_md, :source, NULL, :created_at, :updated_at)
            """
        ),
        params={
            "name": node.name,
            "strategy_md": node.content_md,
            "source": source,
            "created_at": now,
            "updated_at": now,
        },
    )
    return int(result.lastrowid)


def _upsert_skill(session: Session, node: NamedNodeInput) -> int:
    existing = session.exec(
        text("SELECT id FROM skills WHERE name = :name"),
        params={"name": node.name},
    ).first()
    if existing:
        return int(existing.id)

    now = utc_now()
    result = session.exec(
        text(
            """
            INSERT INTO skills(name, content_md, created_at, updated_at)
            VALUES (:name, :content_md, :created_at, :updated_at)
            """
        ),
        params={
            "name": node.name,
            "content_md": node.content_md,
            "created_at": now,
            "updated_at": now,
        },
    )
    return int(result.lastrowid)


def _upsert_pitfall(session: Session, node: NamedNodeInput) -> int:
    existing = session.exec(
        text("SELECT id FROM common_pitfalls WHERE name = :name"),
        params={"name": node.name},
    ).first()
    if existing:
        return int(existing.id)

    now = utc_now()
    result = session.exec(
        text(
            """
            INSERT INTO common_pitfalls(name, content_md, created_at, updated_at)
            VALUES (:name, :content_md, :created_at, :updated_at)
            """
        ),
        params={
            "name": node.name,
            "content_md": node.content_md,
            "created_at": now,
            "updated_at": now,
        },
    )
    return int(result.lastrowid)


def _validate_kp_ids(session: Session, kp_ids: list[WeightedKpInput]) -> None:
    for kp in kp_ids:
        if not session.get(KnowledgePoint, kp.id):
            raise HTTPException(status_code=400, detail=f"Unknown knowledge point: {kp.id}")


def _replace_question_edges(session: Session, question_id: int, payload: QuestionCreate | QuestionUpdate) -> None:
    for table in ("question_kp", "question_patterns_map", "question_skills", "question_pitfalls", "question_tags"):
        session.exec(text(f"DELETE FROM {table} WHERE question_id = :question_id"), params={"question_id": question_id})

    kp_ids = payload.kp_ids or []
    _validate_kp_ids(session, kp_ids)
    for kp in kp_ids:
        session.exec(
            text(
                """
                INSERT INTO question_kp(question_id, kp_id, weight, is_primary)
                VALUES (:question_id, :kp_id, :weight, :is_primary)
                """
            ),
            params={
                "question_id": question_id,
                "kp_id": kp.id,
                "weight": kp.weight,
                "is_primary": 1 if kp.is_primary else 0,
            },
        )

    for node in payload.patterns or []:
        pattern_id = _upsert_pattern(session, node, source="manual")
        session.exec(
            text(
                """
                INSERT INTO question_patterns_map(question_id, pattern_id, weight, is_primary)
                VALUES (:question_id, :pattern_id, :weight, :is_primary)
                """
            ),
            params={
                "question_id": question_id,
                "pattern_id": pattern_id,
                "weight": node.weight,
                "is_primary": 1 if node.is_primary else 0,
            },
        )

    for node in payload.skills or []:
        skill_id = _upsert_skill(session, node)
        session.exec(
            text(
                """
                INSERT INTO question_skills(question_id, skill_id, weight)
                VALUES (:question_id, :skill_id, :weight)
                """
            ),
            params={"question_id": question_id, "skill_id": skill_id, "weight": node.weight},
        )

    for node in payload.pitfalls or []:
        pitfall_id = _upsert_pitfall(session, node)
        session.exec(
            text(
                """
                INSERT INTO question_pitfalls(question_id, pitfall_id, weight)
                VALUES (:question_id, :pitfall_id, :weight)
                """
            ),
            params={"question_id": question_id, "pitfall_id": pitfall_id, "weight": node.weight},
        )

    for tag in payload.tags or []:
        clean_tag = tag.strip()
        if clean_tag:
            session.exec(
                text("INSERT INTO question_tags(question_id, tag) VALUES (:question_id, :tag)"),
                params={"question_id": question_id, "tag": clean_tag},
            )


def create_question(session: Session, payload: QuestionCreate) -> QuestionRead:
    if not payload.stem_md.strip():
        raise HTTPException(status_code=400, detail="stem_md is required")

    q_hash = stem_hash(payload.stem_md)
    existing = session.exec(
        text("SELECT id FROM questions WHERE hash = :hash"),
        params={"hash": q_hash},
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail={"message": "Duplicate question", "id": existing.id})

    now = utc_now()
    result = session.exec(
        text(
            """
            INSERT INTO questions(
              source, format_id, difficulty, stem_md, options_json, answer_key_json,
              answer_md, solution_md, image_path, hash, created_at, updated_at
            )
            VALUES (
              :source, :format_id, :difficulty, :stem_md, :options_json, :answer_key_json,
              :answer_md, :solution_md, :image_path, :hash, :created_at, :updated_at
            )
            """
        ),
        params={
            "source": payload.source,
            "format_id": payload.format_id,
            "difficulty": payload.difficulty,
            "stem_md": payload.stem_md,
            "options_json": _json_dump(payload.options_json),
            "answer_key_json": _json_dump(payload.answer_key_json),
            "answer_md": payload.answer_md,
            "solution_md": payload.solution_md,
            "image_path": payload.image_path,
            "hash": q_hash,
            "created_at": now,
            "updated_at": now,
        },
    )
    question_id = int(result.lastrowid)
    _replace_question_edges(session, question_id, payload)
    session.commit()
    return get_question(session, question_id)


def get_or_create_question(session: Session, payload: QuestionCreate) -> QuestionRead:
    if not payload.stem_md.strip():
        raise HTTPException(status_code=400, detail="stem_md is required")
    q_hash = stem_hash(payload.stem_md)
    existing = session.exec(
        text("SELECT id FROM questions WHERE hash = :hash"),
        params={"hash": q_hash},
    ).first()
    if existing:
        return get_question(session, int(existing.id))
    return create_question(session, payload)


def update_question(session: Session, question_id: int, payload: QuestionUpdate) -> QuestionRead:
    question = session.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    next_stem = payload.stem_md if payload.stem_md is not None else question.stem_md
    q_hash = stem_hash(next_stem)
    duplicate = session.exec(
        text("SELECT id FROM questions WHERE hash = :hash AND id != :question_id"),
        params={"hash": q_hash, "question_id": question_id},
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail={"message": "Duplicate question", "id": duplicate.id})

    fields = {
        "source": payload.source if payload.source is not None else question.source,
        "format_id": payload.format_id if payload.format_id is not None else question.format_id,
        "difficulty": payload.difficulty if payload.difficulty is not None else question.difficulty,
        "stem_md": next_stem,
        "options_json": _json_dump(payload.options_json) if payload.options_json is not None else question.options_json,
        "answer_key_json": _json_dump(payload.answer_key_json) if payload.answer_key_json is not None else question.answer_key_json,
        "answer_md": payload.answer_md if payload.answer_md is not None else question.answer_md,
        "solution_md": payload.solution_md if payload.solution_md is not None else question.solution_md,
        "image_path": payload.image_path if payload.image_path is not None else question.image_path,
        "hash": q_hash,
        "updated_at": utc_now(),
        "question_id": question_id,
    }
    session.exec(
        text(
            """
            UPDATE questions
            SET source = :source,
                format_id = :format_id,
                difficulty = :difficulty,
                stem_md = :stem_md,
                options_json = :options_json,
                answer_key_json = :answer_key_json,
                answer_md = :answer_md,
                solution_md = :solution_md,
                image_path = :image_path,
                hash = :hash,
                updated_at = :updated_at
            WHERE id = :question_id
            """
        ),
        params=fields,
    )
    if any(
        value is not None
        for value in (payload.kp_ids, payload.patterns, payload.skills, payload.pitfalls, payload.tags)
    ):
        existing_payload = _payload_from_question(session, question_id)
        edge_payload = QuestionUpdate(
            kp_ids=payload.kp_ids if payload.kp_ids is not None else existing_payload.kp_ids,
            patterns=payload.patterns if payload.patterns is not None else existing_payload.patterns,
            skills=payload.skills if payload.skills is not None else existing_payload.skills,
            pitfalls=payload.pitfalls if payload.pitfalls is not None else existing_payload.pitfalls,
            tags=payload.tags if payload.tags is not None else existing_payload.tags,
        )
        _replace_question_edges(session, question_id, edge_payload)
    session.commit()
    return get_question(session, question_id)


def delete_question(session: Session, question_id: int) -> None:
    if not session.get(Question, question_id):
        raise HTTPException(status_code=404, detail="Question not found")
    session.exec(text("DELETE FROM questions WHERE id = :question_id"), params={"question_id": question_id})
    session.commit()


def list_questions(
    session: Session,
    *,
    kp: str | None = None,
    pattern: int | None = None,
    skill: int | None = None,
    pitfall: int | None = None,
    difficulty: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 30,
) -> QuestionListResponse:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    where = ["1 = 1"]
    params: dict[str, Any] = {}
    if kp:
        where.append("EXISTS (SELECT 1 FROM question_kp qkp WHERE qkp.question_id = questions.id AND qkp.kp_id = :kp)")
        params["kp"] = kp
    if pattern:
        where.append("EXISTS (SELECT 1 FROM question_patterns_map qpm WHERE qpm.question_id = questions.id AND qpm.pattern_id = :pattern)")
        params["pattern"] = pattern
    if skill:
        where.append("EXISTS (SELECT 1 FROM question_skills qs WHERE qs.question_id = questions.id AND qs.skill_id = :skill)")
        params["skill"] = skill
    if pitfall:
        where.append("EXISTS (SELECT 1 FROM question_pitfalls qp WHERE qp.question_id = questions.id AND qp.pitfall_id = :pitfall)")
        params["pitfall"] = pitfall
    if difficulty:
        where.append("questions.difficulty = :difficulty")
        params["difficulty"] = difficulty
    if q:
        where.append("(questions.stem_md LIKE :q OR questions.source LIKE :q OR questions.solution_md LIKE :q)")
        params["q"] = f"%{q}%"

    where_sql = " AND ".join(where)
    total = session.exec(
        text(f"SELECT COUNT(*) AS count FROM questions WHERE {where_sql}"),
        params=params,
    ).one().count
    offset = (page - 1) * page_size
    rows = session.exec(
        text(
            f"""
            SELECT id FROM questions
            WHERE {where_sql}
            ORDER BY updated_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params={**params, "limit": page_size, "offset": offset},
    ).all()
    return QuestionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[get_question(session, int(row.id)) for row in rows],
    )


def get_question(session: Session, question_id: int) -> QuestionRead:
    row = session.exec(
        text(
            """
            SELECT q.*, f.name AS format_name
            FROM questions q
            LEFT JOIN question_formats f ON f.id = q.format_id
            WHERE q.id = :question_id
            """
        ),
        params={"question_id": question_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Question not found")

    return QuestionRead(
        id=row.id,
        source=row.source,
        format_id=row.format_id,
        format_name=row.format_name,
        difficulty=row.difficulty,
        stem_md=row.stem_md,
        options_json=_json_load(row.options_json),
        answer_key_json=_json_load(row.answer_key_json),
        answer_md=row.answer_md,
        solution_md=row.solution_md,
        image_path=row.image_path,
        hash=row.hash,
        created_at=row.created_at,
        updated_at=row.updated_at,
        knowledge_points=_question_kps(session, question_id),
        patterns=_question_nodes(session, question_id, "pattern"),
        skills=_question_nodes(session, question_id, "skill"),
        pitfalls=_question_nodes(session, question_id, "pitfall"),
        tags=[
            tag.tag
            for tag in session.exec(
                text("SELECT tag FROM question_tags WHERE question_id = :question_id ORDER BY tag"),
                params={"question_id": question_id},
            ).all()
        ],
    )


def _question_kps(session: Session, question_id: int):
    rows = session.exec(
        text(
            """
            SELECT kp.*
            FROM knowledge_points kp
            JOIN question_kp qkp ON qkp.kp_id = kp.id
            WHERE qkp.question_id = :question_id
            ORDER BY qkp.is_primary DESC, qkp.weight DESC, kp.order_index
            """
        ),
        params={"question_id": question_id},
    ).all()
    return [_summary(KnowledgePoint.model_validate(dict(row._mapping))) for row in rows]


def _question_nodes(session: Session, question_id: int, kind: str) -> list[GraphNode]:
    table = {
        "pattern": "question_patterns",
        "skill": "skills",
        "pitfall": "common_pitfalls",
    }[kind]
    edge = {
        "pattern": "question_patterns_map",
        "skill": "question_skills",
        "pitfall": "question_pitfalls",
    }[kind]
    key = {
        "pattern": "pattern_id",
        "skill": "skill_id",
        "pitfall": "pitfall_id",
    }[kind]
    rows = session.exec(
        text(
            f"""
            SELECT node.*, edge.weight, {('edge.is_primary' if kind == 'pattern' else '0')} AS is_primary
            FROM {table} node
            JOIN {edge} edge ON edge.{key} = node.id
            WHERE edge.question_id = :question_id
            ORDER BY edge.weight DESC, node.id
            """
        ),
        params={"question_id": question_id},
    ).all()
    nodes: list[GraphNode] = []
    for row in rows:
        nodes.append(
            GraphNode(
                id=row.id,
                name=row.name,
                content_md=getattr(row, "content_md", None),
                source=getattr(row, "source", None),
                strategy_md=getattr(row, "strategy_md", None),
                order_index=getattr(row, "order_index", None),
                weight=row.weight,
                is_primary=bool(row.is_primary),
            )
        )
    return nodes


def _payload_from_question(session: Session, question_id: int) -> QuestionUpdate:
    question = get_question(session, question_id)
    return QuestionUpdate(
        kp_ids=[WeightedKpInput(id=kp.id) for kp in question.knowledge_points],
        patterns=[NamedNodeInput(name=node.name, weight=node.weight or 1.0, is_primary=bool(node.is_primary)) for node in question.patterns],
        skills=[NamedNodeInput(name=node.name, weight=node.weight or 1.0) for node in question.skills],
        pitfalls=[NamedNodeInput(name=node.name, weight=node.weight or 1.0) for node in question.pitfalls],
        tags=question.tags,
    )


def question_from_form_like(payload: dict[str, Any]) -> QuestionCreate:
    return QuestionCreate(
        source=payload.get("source") or None,
        format_id=int(payload["format_id"]) if payload.get("format_id") else None,
        difficulty=int(payload["difficulty"]) if payload.get("difficulty") else None,
        stem_md=payload.get("stem_md") or "",
        answer_md=payload.get("answer_md") or None,
        solution_md=payload.get("solution_md") or None,
        kp_ids=[WeightedKpInput(id=kp_id, is_primary=index == 0) for index, kp_id in enumerate(payload.get("kp_ids", []))],
        patterns=_split_names(payload.get("patterns_text", "")),
        skills=_split_names(payload.get("skills_text", "")),
        pitfalls=_split_names(payload.get("pitfalls_text", "")),
        tags=[tag.strip() for tag in payload.get("tags_text", "").replace("，", ",").split(",") if tag.strip()],
    )
