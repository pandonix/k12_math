from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KnowledgePointSummary(BaseModel):
    id: str
    book: str
    chapter: str | None
    section: str | None
    title: str
    level: int
    tags: list[str]
    facets: list[str]
    order_index: int
    updated_at: datetime


class KnowledgePointDetail(KnowledgePointSummary):
    content_md: str


class ChapterNode(BaseModel):
    chapter: str
    items: list[KnowledgePointSummary]


class BookNode(BaseModel):
    book: str
    chapters: list[ChapterNode]


class KnowledgePointTree(BaseModel):
    count: int
    books: list[BookNode]


class SyncResponse(BaseModel):
    parsed: int
    inserted: int
    updated: int
    deleted_stale: int
    skipped_unchanged: int
    duplicate_ids: list[str]


class GraphKpResponse(BaseModel):
    kp: KnowledgePointDetail
    patterns: list[dict]
    skills: list[dict]
    pitfalls: list[dict]
    questions: list[dict]
    edges: list[dict]
