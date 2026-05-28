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


class WeightedKpInput(BaseModel):
    id: str
    weight: float = 1.0
    is_primary: bool = False


class NamedNodeInput(BaseModel):
    name: str
    content_md: str | None = None
    weight: float = 1.0
    is_primary: bool = False


class QuestionCreate(BaseModel):
    source: str | None = None
    format_id: int | None = None
    difficulty: int | None = None
    stem_md: str
    options_json: list[dict] | None = None
    answer_key_json: dict | None = None
    answer_md: str | None = None
    solution_md: str | None = None
    image_path: str | None = None
    kp_ids: list[WeightedKpInput] = []
    patterns: list[NamedNodeInput] = []
    skills: list[NamedNodeInput] = []
    pitfalls: list[NamedNodeInput] = []
    tags: list[str] = []


class QuestionUpdate(BaseModel):
    source: str | None = None
    format_id: int | None = None
    difficulty: int | None = None
    stem_md: str | None = None
    options_json: list[dict] | None = None
    answer_key_json: dict | None = None
    answer_md: str | None = None
    solution_md: str | None = None
    image_path: str | None = None
    kp_ids: list[WeightedKpInput] | None = None
    patterns: list[NamedNodeInput] | None = None
    skills: list[NamedNodeInput] | None = None
    pitfalls: list[NamedNodeInput] | None = None
    tags: list[str] | None = None


class GraphNode(BaseModel):
    id: int
    name: str
    content_md: str | None = None
    source: str | None = None
    strategy_md: str | None = None
    order_index: int | None = None
    weight: float | None = None
    is_primary: bool | None = None


class QuestionRead(BaseModel):
    id: int
    source: str | None
    format_id: int | None
    format_name: str | None
    difficulty: int | None
    stem_md: str
    options_json: list[dict] | None
    answer_key_json: dict | None
    answer_md: str | None
    solution_md: str | None
    image_path: str | None
    hash: str | None
    created_at: datetime
    updated_at: datetime
    knowledge_points: list[KnowledgePointSummary]
    patterns: list[GraphNode]
    skills: list[GraphNode]
    pitfalls: list[GraphNode]
    tags: list[str]


class QuestionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[QuestionRead]


class PatternCreate(BaseModel):
    name: str
    strategy_md: str | None = None
    source: str | None = None
    kp_ids: list[WeightedKpInput] = []
    skills: list[NamedNodeInput] = []
    pitfalls: list[NamedNodeInput] = []


class PatternRead(BaseModel):
    id: int
    name: str
    strategy_md: str | None
    source: str | None
    order_index: int | None
    knowledge_points: list[KnowledgePointSummary]
    skills: list[GraphNode]
    pitfalls: list[GraphNode]


class EdgeCreate(BaseModel):
    from_type: str
    from_id: int
    to_type: str
    to_id: int | str
    relation: str
    weight: float = 1.0


class DocxImportRequest(BaseModel):
    path: str | None = None


class ParsedQuestionPreview(BaseModel):
    source: str
    question_type: str
    stem: str
    answer: str
    solution: str
    expected_kp: str


class ParsedLearningMaterial(BaseModel):
    source_path: str
    paragraph_count: int
    type_count: int
    question_count: int
    patterns: list[dict]
    questions: list[ParsedQuestionPreview]
