#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "20260530"
DEFAULT_DB_PATH = ROOT / "data" / "math.db"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
V_NS = "urn:schemas-microsoft-com:vml"

BATCH_TAG = "20260530索引"
INDEX_TAG = "索引题"


@dataclass(frozen=True)
class Paragraph:
    index: int
    text: str


@dataclass(frozen=True)
class SectionNode:
    rel_path: str
    paragraph_index: int
    name: str
    kind: str
    kp_ids: tuple[str, ...]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestionIndex:
    rel_path: str
    paragraph_index: int
    label: str
    section_name: str
    section_kind: str
    kp_ids: tuple[str, ...]
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def source(self) -> str:
        return f"20260530｜{self.rel_path}｜p{self.paragraph_index}｜{self.section_name}｜{self.label}"

    @property
    def stem_md(self) -> str:
        return (
            "【索引题】\n"
            f"- 批次：20260530\n"
            f"- 文档：{self.rel_path}\n"
            f"- 图谱栏目：{self.section_name}\n"
            f"- 题目标签：{self.label}\n"
            f"- 段落序号：{self.paragraph_index}\n"
            "- 原题干与解析：暂未导入视觉/公式还原内容，请按以上索引回到原 docx 查看。"
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stem_hash(stem_md: str) -> str:
    return hashlib.sha256(stem_md.strip().encode("utf-8")).hexdigest()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_heading(value: str) -> str:
    value = normalize_space(value)
    value = value.replace("[IMG]", "").replace("[OMML]", "")
    value = re.sub(r"\s*\(?共\d+小题\)?\s*$", "", value)
    value = re.sub(r"\s*[（(](?:重点|难点|常考点|易错点)[）)]\s*$", "", value)
    value = re.sub(r"\s*\d+\s*$", "", value)
    return normalize_space(value)


def extract_docx_paragraphs(docx_path: Path) -> list[Paragraph]:
    with ZipFile(docx_path) as docx:
        root = ET.fromstring(docx.read("word/document.xml"))

    paragraphs: list[Paragraph] = []
    para_index = 0
    for para in root.iter(f"{{{W_NS}}}p"):
        parts: list[str] = []
        omath_descendants = {
            id(node) for omath in para.iter(f"{{{M_NS}}}oMath") for node in omath.iter()
        }
        for element in para.iter():
            if element.tag == f"{{{M_NS}}}oMath":
                parts.append("[OMML]")
                continue
            if id(element) in omath_descendants:
                continue
            if element.tag == f"{{{W_NS}}}t" and element.text:
                parts.append(element.text)
            elif element.tag in {f"{{{A_NS}}}blip", f"{{{V_NS}}}imagedata"}:
                parts.append("[IMG]")
        text = normalize_space("".join(parts))
        if text:
            para_index += 1
            paragraphs.append(Paragraph(para_index, text))
    return paragraphs


def load_kp_ids(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["title"]: row["id"]
        for row in conn.execute("SELECT id, title FROM knowledge_points ORDER BY order_index")
    }


def by_title(kps: dict[str, str], *titles: str) -> tuple[str, ...]:
    ids = [kps[title] for title in titles if title in kps]
    return tuple(dict.fromkeys(ids))


def kp_candidates(text: str, rel_path: str, kps: dict[str, str]) -> tuple[str, ...]:
    haystack = f"{rel_path}\n{text}"
    rules: list[tuple[str, tuple[str, ...]]] = [
        (r"复数.*(三角|棣莫弗)", ("7.4 复数的三角表示", "7.3 复数的四则运算")),
        (r"复数.*(几何|复平面|模|共轭)", ("7.2 复数的几何意义", "7.1 复数的概念")),
        (r"复数", ("7.1 复数的概念", "7.3 复数的四则运算")),
        (r"诱导公式", ("5.3 诱导公式",)),
        (r"任意角|弧度|终边", ("5.1 任意角和弧度制",)),
        (r"同角|三角函数.*概念|三角函数定义", ("5.2 三角函数的概念",)),
        (r"图象|单调|周期|对称|Asin|A\\sin|ω|相位|五点", ("5.4 三角函数的图象和性质", "5.6 函数 $y=A\\sin(\\omega x+\\varphi)$")),
        (r"恒等|二倍角|半角|和差|辅助角|降幂|边角互化", ("5.5 三角恒等变换",)),
        (r"正.?余弦|解三角形|面积公式|三角形.*面积|边角互化|角平分线|张角定理", ("6.6 解三角形", "5.5 三角恒等变换")),
        (r"极化|数量积|投影|夹角|垂直", ("6.4 平面向量数量积",)),
        (r"奔驰|四心|爪子|等和线|几何中应用|平面向量在几何", ("6.5 平面向量在几何中的应用", "6.4 平面向量数量积")),
        (r"共线|基本定理|坐标|基底", ("6.3 平面向量基本定理及坐标表示",)),
        (r"线性运算|加.?减|数乘|中点|重心|定比分点", ("6.2 平面向量的线性运算",)),
        (r"平面向量|零向量|单位向量|相等向量|模长", ("6.1 平面向量的概念",)),
        (r"外接球|内切球|棱切球|球心", ("8.7 外接球与内切球",)),
        (r"表面积|体积|棱柱|棱锥|圆柱|圆锥|圆台|球", ("8.3 简单几何体的表面积与体积",)),
        (r"截面|动点|线面位置|异面", ("8.4 空间点、直线、平面之间的位置关系",)),
        (r"平行", ("8.5 空间直线、平面的平行",)),
        (r"垂直", ("8.6 空间直线、平面的垂直",)),
        (r"统计图表|中位数|百分位数|频率分布|总体|样本|方差", ("9.2 用样本估计总体",)),
        (r"随机抽样|抽样", ("9.1 随机抽样",)),
        (r"古典概型|样本点|有放回|不放回", ("10.2 古典概型",)),
        (r"相互独立|独立事件|条件概率", ("10.3 事件的相互独立性",)),
        (r"概率|随机事件", ("10.1 随机事件与概率",)),
    ]

    matched: list[str] = []
    for pattern, titles in rules:
        if re.search(pattern, haystack, re.I):
            matched.extend(by_title(kps, *titles))
    if matched:
        return tuple(dict.fromkeys(matched))[:4]

    folder_defaults = [
        ("02_三角函数", ("5.1 任意角和弧度制", "5.4 三角函数的图象和性质")),
        ("03_平面向量", ("6.1 平面向量的概念", "6.2 平面向量的线性运算")),
        ("04_解三角形", ("6.6 解三角形",)),
        ("05_复数", ("7.1 复数的概念",)),
    ]
    for folder, titles in folder_defaults:
        if rel_path.startswith(folder):
            return by_title(kps, *titles)
    return ()


def section_from_line(line: str, rel_path: str, paragraph_index: int, kps: dict[str, str]) -> SectionNode | None:
    if re.search(r"[（(]P\d+[）)]", line, re.I):
        return None
    patterns = [
        (r"^(方法技巧\d{1,2}\s*.+)$", "skill", ("方法技巧",)),
        (r"^(易混易错\d{1,2}\s*.+)$", "pitfall", ("易混易错",)),
        (r"^(题型[一二三四五六七八九十百]+\.?\s*.+)$", "pattern", ("题型",)),
        (r"^(题型\d{1,2}\s*.+)$", "pattern", ("题型",)),
        (r"^(热点\d{1,2}\s*.+)$", "pattern", ("热点",)),
        (r"^(妙招(?:\[IMG\])?\d{1,2}\s*.+)$", "skill", ("妙招",)),
        (r"^(避坑\d{1,2}\s*.+)$", "pitfall", ("避坑",)),
        (r"^(?:\[IMG\])?(知识点\d{1,2}\s*.+)$", "knowledge", ("知识补充",)),
        (r"^(速查\d{1,2}\s*.+)$", "knowledge", ("速查",)),
    ]
    for pattern, kind, tags in patterns:
        match = re.match(pattern, line)
        if not match:
            continue
        name = clean_heading(match.group(1))
        if not name:
            return None
        return SectionNode(
            rel_path=rel_path,
            paragraph_index=paragraph_index,
            name=name,
            kind=kind,
            kp_ids=kp_candidates(name, rel_path, kps),
            tags=tags,
        )
    return None


def question_label(line: str) -> str | None:
    bracket = re.match(
        r"^【((?:典例|例题|例|变式|跟踪训练|巩固训练|针对训练|高考真题|模拟训练)\d*(?:[-—]\d+)?)】",
        line,
    )
    if bracket:
        return bracket.group(1) or "题目"
    numbered = re.match(r"^(\d{1,3})[．.]\s*(?:（|\()", line)
    if numbered:
        return f"第{numbered.group(1)}题"
    return None


def parse_materials(source_dir: Path, conn: sqlite3.Connection) -> tuple[list[SectionNode], list[QuestionIndex], dict]:
    kps = load_kp_ids(conn)
    sections: list[SectionNode] = []
    questions: list[QuestionIndex] = []
    stats = {
        "documents": 0,
        "paragraphs": 0,
        "sections_by_kind": Counter(),
        "questions_by_folder": Counter(),
    }

    for docx_path in sorted(source_dir.rglob("*.docx")):
        rel_path = str(docx_path.relative_to(source_dir))
        paragraphs = extract_docx_paragraphs(docx_path)
        stats["documents"] += 1
        stats["paragraphs"] += len(paragraphs)

        current_section = SectionNode(
            rel_path=rel_path,
            paragraph_index=1,
            name=clean_heading(docx_path.stem),
            kind="document",
            kp_ids=kp_candidates(docx_path.stem, rel_path, kps),
            tags=("文档",),
        )
        sections.append(current_section)
        stats["sections_by_kind"][current_section.kind] += 1

        for paragraph in paragraphs:
            section = section_from_line(paragraph.text, rel_path, paragraph.index, kps)
            if section:
                current_section = section
                sections.append(section)
                stats["sections_by_kind"][section.kind] += 1
                continue

            label = question_label(paragraph.text)
            if not label:
                continue
            if current_section.kind in {"document", "knowledge"} and label.startswith("第"):
                # Numbered lines in pure knowledge-list areas are often bullets,
                # unless the surrounding document has an exam/hotspot section.
                if not re.search(r"考前最后一课|热点|押题|实训|专题|培优", current_section.name + rel_path):
                    continue
            kp_ids = kp_candidates(
                f"{current_section.name}\n{paragraph.text}",
                rel_path,
                kps,
            ) or current_section.kp_ids
            questions.append(
                QuestionIndex(
                    rel_path=rel_path,
                    paragraph_index=paragraph.index,
                    label=label,
                    section_name=current_section.name,
                    section_kind=current_section.kind,
                    kp_ids=kp_ids,
                    tags=tuple(dict.fromkeys((BATCH_TAG, INDEX_TAG, *current_section.tags))),
                )
            )
            folder = rel_path.split("/", 1)[0]
            stats["questions_by_folder"][folder] += 1

    unique_sections = list({(item.kind, item.name): item for item in sections}.values())
    stats["sections"] = len(unique_sections)
    stats["questions"] = len(questions)
    stats["sections_by_kind"] = dict(stats["sections_by_kind"])
    stats["questions_by_folder"] = dict(stats["questions_by_folder"])
    return unique_sections, questions, stats


def upsert_pattern(conn: sqlite3.Connection, name: str, source: str, strategy_md: str | None = None) -> int:
    row = conn.execute("SELECT id FROM question_patterns WHERE name = ? ORDER BY id LIMIT 1", (name,)).fetchone()
    if row:
        return int(row["id"])
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO question_patterns(name, strategy_md, source, order_index, created_at, updated_at)
        VALUES (?, ?, ?, NULL, ?, ?)
        """,
        (name, strategy_md, source, now, now),
    )
    return int(cursor.lastrowid)


def upsert_named_node(conn: sqlite3.Connection, table: str, name: str, content_col: str, content_md: str | None) -> int:
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    now = utc_now()
    cursor = conn.execute(
        f"INSERT INTO {table}(name, {content_col}, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, content_md, now, now),
    )
    return int(cursor.lastrowid)


def insert_pattern_edges(
    conn: sqlite3.Connection,
    pattern_id: int,
    kp_ids: tuple[str, ...],
    *,
    skill_id: int | None = None,
    pitfall_id: int | None = None,
) -> None:
    for index, kp_id in enumerate(kp_ids):
        weight = 1.0 if index == 0 else max(0.55, 0.85 - index * 0.1)
        conn.execute(
            """
            INSERT OR REPLACE INTO pattern_kp(pattern_id, kp_id, weight, relation)
            VALUES (?, ?, ?, 'tests')
            """,
            (pattern_id, kp_id, weight),
        )
    if skill_id is not None:
        conn.execute(
            "INSERT OR REPLACE INTO pattern_skills(pattern_id, skill_id, weight) VALUES (?, ?, 1.0)",
            (pattern_id, skill_id),
        )
    if pitfall_id is not None:
        conn.execute(
            "INSERT OR REPLACE INTO pattern_pitfalls(pattern_id, pitfall_id, weight) VALUES (?, ?, 1.0)",
            (pattern_id, pitfall_id),
        )


def upsert_question_index(conn: sqlite3.Connection, item: QuestionIndex) -> int:
    row = conn.execute("SELECT id FROM questions WHERE source = ?", (item.source,)).fetchone()
    now = utc_now()
    if row:
        question_id = int(row["id"])
        conn.execute(
            """
            UPDATE questions
            SET stem_md = ?, hash = ?, updated_at = ?
            WHERE id = ?
            """,
            (item.stem_md, stem_hash(item.stem_md), now, question_id),
        )
        for table in ("question_kp", "question_patterns_map", "question_skills", "question_pitfalls", "question_tags"):
            conn.execute(f"DELETE FROM {table} WHERE question_id = ?", (question_id,))
        return question_id

    cursor = conn.execute(
        """
        INSERT INTO questions(
          source, format_id, difficulty, stem_md, options_json, answer_key_json,
          answer_md, solution_md, image_path, hash, created_at, updated_at
        )
        VALUES (?, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?)
        """,
        (item.source, item.stem_md, stem_hash(item.stem_md), now, now),
    )
    return int(cursor.lastrowid)


def apply_import(conn: sqlite3.Connection, sections: list[SectionNode], questions: list[QuestionIndex]) -> dict:
    pattern_ids: dict[str, int] = {}
    skill_ids: dict[str, int] = {}
    pitfall_ids: dict[str, int] = {}

    for section in sections:
        strategy = f"20260530 来源：{section.rel_path}#p{section.paragraph_index}"
        skill_id = None
        pitfall_id = None
        if section.kind in {"skill", "knowledge"}:
            skill_id = upsert_named_node(conn, "skills", section.name, "content_md", strategy)
            skill_ids[section.name] = skill_id
        if section.kind == "pitfall":
            pitfall_id = upsert_named_node(conn, "common_pitfalls", section.name, "content_md", strategy)
            pitfall_ids[section.name] = pitfall_id
        # Only genuine 题型 (and 热点, also classified as "pattern") become
        # question_patterns. 技巧 / 易错点 / 知识补充 / document headings are their
        # own node types and must not be duplicated into the pattern table
        # (PLAN §3.1/§5.1 — node types are mutually exclusive).
        if section.kind == "pattern":
            pattern_id = upsert_pattern(conn, section.name, "20260530", strategy)
            pattern_ids[section.name] = pattern_id
            insert_pattern_edges(conn, pattern_id, section.kp_ids)

    inserted_or_updated = 0
    for item in questions:
        skill_id = None
        pitfall_id = None
        if item.section_kind in {"skill", "knowledge"}:
            skill_id = skill_ids.get(item.section_name)
            if skill_id is None:
                skill_id = upsert_named_node(conn, "skills", item.section_name, "content_md", None)
                skill_ids[item.section_name] = skill_id
        if item.section_kind == "pitfall":
            pitfall_id = pitfall_ids.get(item.section_name)
            if pitfall_id is None:
                pitfall_id = upsert_named_node(conn, "common_pitfalls", item.section_name, "content_md", None)
                pitfall_ids[item.section_name] = pitfall_id

        question_id = upsert_question_index(conn, item)
        inserted_or_updated += 1
        # belongs_to only for genuine 题型 sections; questions under a
        # 技巧/易错点/知识 section attach via question_skills/pitfalls + question_kp.
        if item.section_kind == "pattern":
            pattern_id = pattern_ids.get(item.section_name)
            if pattern_id is None:
                pattern_id = upsert_pattern(conn, item.section_name, "20260530")
                pattern_ids[item.section_name] = pattern_id
            conn.execute(
                """
                INSERT OR REPLACE INTO question_patterns_map(question_id, pattern_id, weight, is_primary)
                VALUES (?, ?, 1.0, 1)
                """,
                (question_id, pattern_id),
            )
        for index, kp_id in enumerate(item.kp_ids):
            conn.execute(
                """
                INSERT OR REPLACE INTO question_kp(question_id, kp_id, weight, is_primary)
                VALUES (?, ?, ?, ?)
                """,
                (question_id, kp_id, 1.0 if index == 0 else 0.75, 1 if index == 0 else 0),
            )
        if skill_id is not None:
            conn.execute(
                "INSERT OR REPLACE INTO question_skills(question_id, skill_id, weight) VALUES (?, ?, 1.0)",
                (question_id, skill_id),
            )
        if pitfall_id is not None:
            conn.execute(
                "INSERT OR REPLACE INTO question_pitfalls(question_id, pitfall_id, weight) VALUES (?, ?, 1.0)",
                (question_id, pitfall_id),
            )
        for tag in item.tags:
            conn.execute(
                "INSERT OR IGNORE INTO question_tags(question_id, tag) VALUES (?, ?)",
                (question_id, tag),
            )

    return {
        "sections_upserted": len(sections),
        "questions_upserted": inserted_or_updated,
        "patterns_seen": len(pattern_ids),
        "skills_seen": len(skill_ids),
        "pitfalls_seen": len(pitfall_ids),
    }


def backup_db(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.name}.before-20260530-graph.{stamp}.bak")
    shutil.copy2(db_path, backup_path)
    return backup_path


def summarize_db(conn: sqlite3.Connection) -> dict:
    names = [
        "questions",
        "question_patterns",
        "skills",
        "common_pitfalls",
        "question_kp",
        "question_patterns_map",
        "question_skills",
        "question_pitfalls",
        "pattern_kp",
        "pattern_skills",
        "pattern_pitfalls",
    ]
    return {
        name: conn.execute(f"SELECT COUNT(*) AS count FROM {name}").fetchone()["count"]
        for name in names
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import 20260530 materials as knowledge-graph nodes and document question indexes."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--apply", action="store_true", help="Write to SQLite. Without this flag, only prints a dry-run report.")
    args = parser.parse_args()

    if not args.source_dir.exists():
        raise SystemExit(f"source dir not found: {args.source_dir}")
    if not args.db.exists():
        raise SystemExit(f"database not found: {args.db}")

    with sqlite3.connect(args.db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        before = summarize_db(conn)
        sections, questions, stats = parse_materials(args.source_dir, conn)

    report = {
        "source_dir": str(args.source_dir),
        "db": str(args.db),
        "dry_run": not args.apply,
        "parsed": stats,
        "sample_sections": [
            {"kind": item.kind, "name": item.name, "kp_ids": item.kp_ids, "source": f"{item.rel_path}#p{item.paragraph_index}"}
            for item in sections[:8]
        ],
        "sample_questions": [
            {"source": item.source, "kp_ids": item.kp_ids, "tags": item.tags}
            for item in questions[:8]
        ],
        "db_before": before,
    }

    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    backup = backup_db(args.db)
    with sqlite3.connect(args.db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        result = apply_import(conn, sections, questions)
        conn.commit()
        after = summarize_db(conn)

    report["backup"] = str(backup) if backup else None
    report["applied"] = result
    report["db_after"] = after
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)
