from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from backend.db import get_session
from backend.models import KnowledgePoint
from backend.schemas import (
    BookNode,
    ChapterNode,
    KnowledgePointDetail,
    KnowledgePointSummary,
    KnowledgePointTree,
)


router = APIRouter(prefix="/api/kp", tags=["knowledge-points"])


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def _summary(kp: KnowledgePoint) -> KnowledgePointSummary:
    return KnowledgePointSummary(
        id=kp.id,
        book=kp.book,
        chapter=kp.chapter,
        section=kp.section,
        title=kp.title,
        level=kp.level,
        tags=_json_list(kp.tags_json),
        facets=_json_list(kp.facets_json),
        order_index=kp.order_index,
        updated_at=kp.updated_at,
    )


def _detail(kp: KnowledgePoint) -> KnowledgePointDetail:
    return KnowledgePointDetail(
        **_summary(kp).model_dump(),
        content_md=kp.content_md,
    )


@router.get("", response_model=list[KnowledgePointDetail])
def list_knowledge_points(
    book: str | None = None,
    chapter: str | None = None,
    tag: str | None = None,
    q: str | None = Query(default=None, description="Plain substring search over title and content"),
    session: Session = Depends(get_session),
) -> list[KnowledgePointDetail]:
    points = session.exec(select(KnowledgePoint).order_by(KnowledgePoint.order_index)).all()
    query = (q or "").strip().lower()
    output: list[KnowledgePointDetail] = []
    for kp in points:
        tags = _json_list(kp.tags_json)
        if book and kp.book != book:
            continue
        if chapter and kp.chapter != chapter:
            continue
        if tag and tag not in tags:
            continue
        if query and query not in f"{kp.book} {kp.chapter} {kp.title} {kp.content_md}".lower():
            continue
        output.append(_detail(kp))
    return output


@router.get("/tree", response_model=KnowledgePointTree)
def knowledge_tree(session: Session = Depends(get_session)) -> KnowledgePointTree:
    points = session.exec(select(KnowledgePoint).order_by(KnowledgePoint.order_index)).all()
    books: dict[str, dict[str, list[KnowledgePointSummary]]] = {}
    for kp in points:
        book = kp.book or "未分册"
        chapter = kp.chapter or kp.section or "未分章"
        books.setdefault(book, {}).setdefault(chapter, []).append(_summary(kp))

    return KnowledgePointTree(
        count=len(points),
        books=[
            BookNode(
                book=book,
                chapters=[
                    ChapterNode(chapter=chapter, items=items)
                    for chapter, items in chapters.items()
                ],
            )
            for book, chapters in books.items()
        ],
    )


@router.get("/{kp_id}", response_model=KnowledgePointDetail)
def get_knowledge_point(
    kp_id: str,
    session: Session = Depends(get_session),
) -> KnowledgePointDetail:
    kp = session.get(KnowledgePoint, kp_id)
    if not kp:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    return _detail(kp)
