from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MD_PATH = PROJECT_ROOT / "高一数学知识点总整理（人教A版必修一二详版）.md"


@dataclass(frozen=True)
class ParsedKnowledgePoint:
    id: str
    book: str
    chapter: str
    section: str
    title: str
    level: int
    parent_id: str | None
    content_md: str
    tags: list[str]
    facets: list[str]
    order_index: int
    content_md5: str
    legacy_id_formula: str
    updated_at: str


@dataclass(frozen=True)
class SyncResult:
    parsed: int
    inserted: int
    updated: int
    deleted_stale: int
    skipped_unchanged: int
    duplicate_ids: list[str]


def js_int32(value: int) -> int:
    value &= 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value


def base36(value: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    out: list[str] = []
    while value:
        value, rem = divmod(value, 36)
        out.append(chars[rem])
    return "".join(reversed(out))


def slugify_js(text_value: str) -> str:
    hash_value = 0
    for char in text_value:
        hash_value = js_int32(js_int32(hash_value << 5) - hash_value + ord(char))
    return f"k-{base36(abs(hash_value))}"


def strip_markdown(markdown: str) -> str:
    text_value = re.sub(r"```[\s\S]*?```", " ", markdown)
    text_value = re.sub(r"\$\$([\s\S]*?)\$\$", r" \1 ", text_value)
    text_value = re.sub(r"[#>*_|`\[\](){}\\]", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def infer_tags(title: str, content: str) -> list[str]:
    text_value = f"{title}\n{content}"
    tags: list[str] = []
    if re.search(r"\$\$|公式|定理|恒等式|运算律|坐标公式|面积公式|体积|表面积|半径", text_value):
        tags.append("公式")
    if re.search(r"高频考点|典型题型|常用思路", text_value):
        tags.append("考点")
    if re.search(r"易错提醒|易错点", text_value):
        tags.append("易错")
    if "二级结论" in text_value:
        tags.append("二级结论")
    return tags


def extract_facets(content: str) -> list[str]:
    return [match.group(2).strip() for match in re.finditer(r"^(#{4})\s+(.+)$", content, re.M)]


def parse_knowledge_markdown(markdown: str) -> list[ParsedKnowledgePoint]:
    lines = markdown.replace("\r\n", "\n").split("\n")
    items: list[ParsedKnowledgePoint] = []
    book = ""
    chapter = ""
    current: dict | None = None

    def push_current() -> None:
        nonlocal current
        if not current:
            return

        content = "\n".join(current["lines"]).strip()
        title = clean_title(current["title"])
        order_index = len(items)
        legacy_formula = f"{current['book']}-{current['chapter']}-{current['raw_title']}-{order_index}"
        item_id = slugify_js(legacy_formula)
        items.append(
            ParsedKnowledgePoint(
                id=item_id,
                book=current["book"],
                chapter=current["chapter"],
                section=title,
                title=title,
                level=current["level"],
                parent_id=None,
                content_md=content,
                tags=infer_tags(title, content),
                facets=extract_facets(content),
                order_index=order_index,
                content_md5=hashlib.md5(content.encode("utf-8")).hexdigest(),
                legacy_id_formula=legacy_formula,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        current = None

    for line in lines:
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if not heading:
            if current:
                current["lines"].append(line)
            continue

        level = len(heading.group(1))
        title = heading.group(2).strip()

        if level == 1:
            push_current()
            if title.startswith("必修") or title.startswith("附录"):
                book = "附录" if "附录" in title else title
                chapter = title if "附录" in title else ""
            else:
                book = ""
                chapter = ""
            continue

        if level == 2:
            if book == "附录":
                push_current()
                current = {
                    "book": book,
                    "chapter": chapter,
                    "raw_title": title,
                    "title": title,
                    "level": level,
                    "lines": [],
                }
                continue
            push_current()
            chapter = title
            continue

        if level == 3:
            push_current()
            current = {
                "book": book,
                "chapter": chapter,
                "raw_title": title,
                "title": title,
                "level": level,
                "lines": [],
            }
            continue

        if current:
            current["lines"].append(line)

    push_current()
    return items


def find_duplicate_ids(items: list[ParsedKnowledgePoint]) -> list[str]:
    counts = Counter(item.id for item in items)
    return sorted(item_id for item_id, count in counts.items() if count > 1)


def load_knowledge_points(path: Path = DEFAULT_MD_PATH) -> list[ParsedKnowledgePoint]:
    markdown = path.read_text(encoding="utf-8")
    return parse_knowledge_markdown(markdown)


def sync_knowledge_points(
    session: Session,
    markdown_path: Path = DEFAULT_MD_PATH,
) -> SyncResult:
    items = load_knowledge_points(markdown_path)
    duplicate_ids = find_duplicate_ids(items)
    if duplicate_ids:
        return SyncResult(
            parsed=len(items),
            inserted=0,
            updated=0,
            deleted_stale=0,
            skipped_unchanged=0,
            duplicate_ids=duplicate_ids,
        )

    existing = {
        row.id: row
        for row in session.exec(text("SELECT id, content_md5 FROM knowledge_points")).all()
    }
    inserted = 0
    updated = 0
    skipped = 0

    for item in items:
        payload = {
            "id": item.id,
            "book": item.book,
            "chapter": item.chapter,
            "section": item.section,
            "title": item.title,
            "level": item.level,
            "parent_id": item.parent_id,
            "content_md": item.content_md,
            "tags_json": json.dumps(item.tags, ensure_ascii=False),
            "facets_json": json.dumps(item.facets, ensure_ascii=False),
            "order_index": item.order_index,
            "content_md5": item.content_md5,
            "legacy_id_formula": item.legacy_id_formula,
            "updated_at": item.updated_at,
        }
        current = existing.get(item.id)
        if current is None:
            session.exec(
                text(
                    """
                    INSERT INTO knowledge_points (
                      id, book, chapter, section, title, level, parent_id,
                      content_md, tags_json, facets_json, order_index,
                      content_md5, legacy_id_formula, updated_at
                    ) VALUES (
                      :id, :book, :chapter, :section, :title, :level, :parent_id,
                      :content_md, :tags_json, :facets_json, :order_index,
                      :content_md5, :legacy_id_formula, :updated_at
                    )
                    """
                ),
                params=payload,
            )
            inserted += 1
        elif current.content_md5 != item.content_md5:
            session.exec(
                text(
                    """
                    UPDATE knowledge_points
                    SET book = :book,
                        chapter = :chapter,
                        section = :section,
                        title = :title,
                        level = :level,
                        parent_id = :parent_id,
                        content_md = :content_md,
                        tags_json = :tags_json,
                        facets_json = :facets_json,
                        order_index = :order_index,
                        content_md5 = :content_md5,
                        legacy_id_formula = :legacy_id_formula,
                        updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                params=payload,
            )
            updated += 1
        else:
            skipped += 1

    deleted_stale = _delete_unreferenced_stale_points(session, {item.id for item in items})
    session.commit()
    return SyncResult(
        parsed=len(items),
        inserted=inserted,
        updated=updated,
        deleted_stale=deleted_stale,
        skipped_unchanged=skipped,
        duplicate_ids=[],
    )


def _delete_unreferenced_stale_points(session: Session, active_ids: set[str]) -> int:
    if not active_ids:
        return 0

    stale_ids = [
        row.id
        for row in session.exec(text("SELECT id FROM knowledge_points")).all()
        if row.id not in active_ids
    ]
    deleted = 0
    for kp_id in stale_ids:
        references = session.exec(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM question_kp WHERE kp_id = :kp_id) +
                  (SELECT COUNT(*) FROM pattern_kp WHERE kp_id = :kp_id) +
                  (SELECT COUNT(*) FROM mistake_diagnoses WHERE kp_id = :kp_id) +
                  (SELECT COUNT(*) FROM personal_weaknesses WHERE kp_id = :kp_id)
                AS reference_count
                """
            ),
            params={"kp_id": kp_id},
        ).one().reference_count
        if references:
            continue
        session.exec(text("DELETE FROM knowledge_points WHERE id = :kp_id"), params={"kp_id": kp_id})
        deleted += 1
    return deleted
