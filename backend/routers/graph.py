from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, text

from backend.db import get_session
from backend.models import KnowledgePoint
from backend.routers.kp import _detail
from backend.schemas import EdgeCreate, GraphKpResponse, GraphNode, NamedNodeInput, PatternCreate, PatternRead
from backend.services.question_store import _upsert_pattern, _upsert_pitfall, _upsert_skill, utc_now


router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/kp/{kp_id}", response_model=GraphKpResponse)
def get_kp_graph(kp_id: str, session: Session = Depends(get_session)) -> GraphKpResponse:
    kp = session.get(KnowledgePoint, kp_id)
    if not kp:
        raise HTTPException(status_code=404, detail="Knowledge point not found")

    return GraphKpResponse(
        kp=_detail(kp),
        patterns=[node.model_dump() for node in _patterns_for_kp(session, kp_id)],
        skills=[node.model_dump() for node in _skills_for_kp(session, kp_id)],
        pitfalls=[node.model_dump() for node in _pitfalls_for_kp(session, kp_id)],
        questions=[dict(row._mapping) for row in _questions_for_kp(session, kp_id)],
        edges=[],
    )


@router.get("/patterns", response_model=list[PatternRead])
def list_patterns(kp: str | None = None, session: Session = Depends(get_session)) -> list[PatternRead]:
    if kp:
        rows = session.exec(
            text(
                """
                SELECT p.*
                FROM question_patterns p
                JOIN pattern_kp pk ON pk.pattern_id = p.id
                WHERE pk.kp_id = :kp
                ORDER BY p.order_index IS NULL, p.order_index, p.id
                """
            ),
            params={"kp": kp},
        ).all()
    else:
        rows = session.exec(
            text("SELECT * FROM question_patterns ORDER BY order_index IS NULL, order_index, id")
        ).all()
    return [_pattern_read(session, int(row.id)) for row in rows]


@router.post("/patterns", response_model=PatternRead, status_code=201)
def create_pattern(payload: PatternCreate, session: Session = Depends(get_session)) -> PatternRead:
    pattern_id = _upsert_pattern(
        session,
        NamedNodeInput(name=payload.name, content_md=payload.strategy_md),
        source=payload.source or "manual",
    )
    session.exec(
        text(
            """
            UPDATE question_patterns
            SET strategy_md = COALESCE(:strategy_md, strategy_md),
                source = COALESCE(:source, source),
                updated_at = :updated_at
            WHERE id = :pattern_id
            """
        ),
        params={
            "strategy_md": payload.strategy_md,
            "source": payload.source or "manual",
            "updated_at": utc_now(),
            "pattern_id": pattern_id,
        },
    )
    _replace_pattern_edges(session, pattern_id, payload)
    session.commit()
    return _pattern_read(session, pattern_id)


@router.get("/patterns/{pattern_id}", response_model=PatternRead)
def get_pattern(pattern_id: int, session: Session = Depends(get_session)) -> PatternRead:
    return _pattern_read(session, pattern_id)


@router.post("/edges", status_code=204)
def create_edge(payload: EdgeCreate, session: Session = Depends(get_session)) -> None:
    _insert_edge(session, payload)
    session.commit()


def _pattern_read(session: Session, pattern_id: int) -> PatternRead:
    row = session.exec(
        text("SELECT * FROM question_patterns WHERE id = :pattern_id"),
        params={"pattern_id": pattern_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return PatternRead(
        id=row.id,
        name=row.name,
        strategy_md=row.strategy_md,
        source=row.source,
        order_index=row.order_index,
        knowledge_points=[
            _summary_from_row(kp_row)
            for kp_row in session.exec(
                text(
                    """
                    SELECT kp.*
                    FROM knowledge_points kp
                    JOIN pattern_kp pk ON pk.kp_id = kp.id
                    WHERE pk.pattern_id = :pattern_id
                    ORDER BY pk.weight DESC, kp.order_index
                    """
                ),
                params={"pattern_id": pattern_id},
            ).all()
        ],
        skills=_pattern_nodes(session, pattern_id, "skill"),
        pitfalls=_pattern_nodes(session, pattern_id, "pitfall"),
    )


def _replace_pattern_edges(session: Session, pattern_id: int, payload: PatternCreate) -> None:
    for table in ("pattern_kp", "pattern_skills", "pattern_pitfalls"):
        session.exec(text(f"DELETE FROM {table} WHERE pattern_id = :pattern_id"), params={"pattern_id": pattern_id})
    for kp in payload.kp_ids:
        if not session.get(KnowledgePoint, kp.id):
            raise HTTPException(status_code=400, detail=f"Unknown knowledge point: {kp.id}")
        session.exec(
            text(
                """
                INSERT INTO pattern_kp(pattern_id, kp_id, weight, relation)
                VALUES (:pattern_id, :kp_id, :weight, 'tests')
                """
            ),
            params={"pattern_id": pattern_id, "kp_id": kp.id, "weight": kp.weight},
        )
    for node in payload.skills:
        skill_id = _upsert_skill(session, node)
        session.exec(
            text(
                """
                INSERT INTO pattern_skills(pattern_id, skill_id, weight)
                VALUES (:pattern_id, :skill_id, :weight)
                """
            ),
            params={"pattern_id": pattern_id, "skill_id": skill_id, "weight": node.weight},
        )
    for node in payload.pitfalls:
        pitfall_id = _upsert_pitfall(session, node)
        session.exec(
            text(
                """
                INSERT INTO pattern_pitfalls(pattern_id, pitfall_id, weight)
                VALUES (:pattern_id, :pitfall_id, :weight)
                """
            ),
            params={"pattern_id": pattern_id, "pitfall_id": pitfall_id, "weight": node.weight},
        )


def _insert_edge(session: Session, payload: EdgeCreate) -> None:
    route = (payload.from_type, payload.to_type, payload.relation)
    if route in {("pattern", "kp", "tests"), ("pattern", "kp", "requires"), ("pattern", "kp", "extends")}:
        session.exec(
            text(
                """
                INSERT OR REPLACE INTO pattern_kp(pattern_id, kp_id, weight, relation)
                VALUES (:from_id, :to_id, :weight, :relation)
                """
            ),
            params=payload.model_dump(),
        )
        return
    if route == ("pattern", "skill", "uses"):
        session.exec(
            text("INSERT OR REPLACE INTO pattern_skills(pattern_id, skill_id, weight) VALUES (:from_id, :to_id, :weight)"),
            params=payload.model_dump(),
        )
        return
    if route == ("pattern", "pitfall", "has_pitfall"):
        session.exec(
            text("INSERT OR REPLACE INTO pattern_pitfalls(pattern_id, pitfall_id, weight) VALUES (:from_id, :to_id, :weight)"),
            params=payload.model_dump(),
        )
        return
    if route == ("question", "kp", "tests"):
        session.exec(
            text("INSERT OR REPLACE INTO question_kp(question_id, kp_id, weight, is_primary) VALUES (:from_id, :to_id, :weight, 0)"),
            params=payload.model_dump(),
        )
        return
    if route == ("question", "pattern", "belongs_to"):
        session.exec(
            text("INSERT OR REPLACE INTO question_patterns_map(question_id, pattern_id, weight, is_primary) VALUES (:from_id, :to_id, :weight, 0)"),
            params=payload.model_dump(),
        )
        return
    if route == ("question", "skill", "uses"):
        session.exec(
            text("INSERT OR REPLACE INTO question_skills(question_id, skill_id, weight) VALUES (:from_id, :to_id, :weight)"),
            params=payload.model_dump(),
        )
        return
    if route == ("question", "pitfall", "has_pitfall"):
        session.exec(
            text("INSERT OR REPLACE INTO question_pitfalls(question_id, pitfall_id, weight) VALUES (:from_id, :to_id, :weight)"),
            params=payload.model_dump(),
        )
        return
    raise HTTPException(status_code=400, detail="Unsupported graph edge")


def _patterns_for_kp(session: Session, kp_id: str) -> list[GraphNode]:
    rows = session.exec(
        text(
            """
            SELECT p.*, MAX(source_edges.weight) AS weight
            FROM question_patterns p
            JOIN (
              SELECT pattern_id, weight
              FROM pattern_kp
              WHERE kp_id = :kp_id
              UNION ALL
              SELECT qpm.pattern_id, qpm.weight
              FROM question_patterns_map qpm
              JOIN question_kp qk ON qk.question_id = qpm.question_id
              WHERE qk.kp_id = :kp_id
            ) source_edges ON source_edges.pattern_id = p.id
            GROUP BY p.id
            ORDER BY weight DESC, p.id
            """
        ),
        params={"kp_id": kp_id},
    ).all()
    return [
        GraphNode(id=row.id, name=row.name, strategy_md=row.strategy_md, source=row.source, order_index=row.order_index, weight=row.weight)
        for row in rows
    ]


def _skills_for_kp(session: Session, kp_id: str) -> list[GraphNode]:
    rows = session.exec(
        text(
            """
            SELECT DISTINCT s.*, COALESCE(ps.weight, qs.weight) AS weight
            FROM skills s
            LEFT JOIN pattern_skills ps ON ps.skill_id = s.id
            LEFT JOIN pattern_kp pk ON pk.pattern_id = ps.pattern_id
            LEFT JOIN question_skills qs ON qs.skill_id = s.id
            LEFT JOIN question_kp qk ON qk.question_id = qs.question_id
            WHERE pk.kp_id = :kp_id OR qk.kp_id = :kp_id
            ORDER BY s.id
            """
        ),
        params={"kp_id": kp_id},
    ).all()
    return [GraphNode(id=row.id, name=row.name, content_md=row.content_md, weight=row.weight) for row in rows]


def _pitfalls_for_kp(session: Session, kp_id: str) -> list[GraphNode]:
    rows = session.exec(
        text(
            """
            SELECT DISTINCT p.*, COALESCE(pp.weight, qp.weight) AS weight
            FROM common_pitfalls p
            LEFT JOIN pattern_pitfalls pp ON pp.pitfall_id = p.id
            LEFT JOIN pattern_kp pk ON pk.pattern_id = pp.pattern_id
            LEFT JOIN question_pitfalls qp ON qp.pitfall_id = p.id
            LEFT JOIN question_kp qk ON qk.question_id = qp.question_id
            WHERE pk.kp_id = :kp_id OR qk.kp_id = :kp_id
            ORDER BY p.id
            """
        ),
        params={"kp_id": kp_id},
    ).all()
    return [GraphNode(id=row.id, name=row.name, content_md=row.content_md, weight=row.weight) for row in rows]


def _questions_for_kp(session: Session, kp_id: str):
    return session.exec(
        text(
            """
            SELECT q.id, q.source, q.difficulty, q.stem_md, q.updated_at, qk.weight, qk.is_primary
            FROM questions q
            JOIN question_kp qk ON qk.question_id = q.id
            WHERE qk.kp_id = :kp_id
            ORDER BY qk.is_primary DESC, qk.weight DESC, q.id DESC
            LIMIT 20
            """
        ),
        params={"kp_id": kp_id},
    ).all()


def _pattern_nodes(session: Session, pattern_id: int, kind: str) -> list[GraphNode]:
    table = "skills" if kind == "skill" else "common_pitfalls"
    edge_table = "pattern_skills" if kind == "skill" else "pattern_pitfalls"
    key = "skill_id" if kind == "skill" else "pitfall_id"
    rows = session.exec(
        text(
            f"""
            SELECT node.*, edge.weight
            FROM {table} node
            JOIN {edge_table} edge ON edge.{key} = node.id
            WHERE edge.pattern_id = :pattern_id
            ORDER BY edge.weight DESC, node.id
            """
        ),
        params={"pattern_id": pattern_id},
    ).all()
    return [GraphNode(id=row.id, name=row.name, content_md=row.content_md, weight=row.weight) for row in rows]


def _summary_from_row(row):
    from backend.routers.kp import _summary

    return _summary(KnowledgePoint.model_validate(dict(row._mapping)))
