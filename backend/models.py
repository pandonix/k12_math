from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class KnowledgePoint(SQLModel, table=True):
    __tablename__ = "knowledge_points"

    id: str = Field(primary_key=True)
    book: str
    chapter: str | None = None
    section: str | None = None
    title: str
    level: int
    parent_id: str | None = Field(default=None, foreign_key="knowledge_points.id")
    content_md: str
    tags_json: str | None = None
    facets_json: str | None = None
    order_index: int
    content_md5: str
    legacy_id_formula: str
    updated_at: datetime
