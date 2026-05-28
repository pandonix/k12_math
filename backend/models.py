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


class QuestionFormat(SQLModel, table=True):
    __tablename__ = "question_formats"

    id: int = Field(primary_key=True)
    name: str


class Question(SQLModel, table=True):
    __tablename__ = "questions"

    id: int | None = Field(default=None, primary_key=True)
    source: str | None = None
    format_id: int | None = Field(default=None, foreign_key="question_formats.id")
    difficulty: int | None = None
    stem_md: str
    options_json: str | None = None
    answer_key_json: str | None = None
    answer_md: str | None = None
    solution_md: str | None = None
    image_path: str | None = None
    hash: str | None = None
    created_at: datetime
    updated_at: datetime


class QuestionPattern(SQLModel, table=True):
    __tablename__ = "question_patterns"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    strategy_md: str | None = None
    source: str | None = None
    order_index: int | None = None
    created_at: datetime
    updated_at: datetime


class Skill(SQLModel, table=True):
    __tablename__ = "skills"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    content_md: str | None = None
    created_at: datetime
    updated_at: datetime


class CommonPitfall(SQLModel, table=True):
    __tablename__ = "common_pitfalls"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    content_md: str | None = None
    created_at: datetime
    updated_at: datetime
