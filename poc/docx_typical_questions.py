#!/usr/bin/env python3
"""Extract typical-question blocks from a DOCX handout into POC question md."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCX = ROOT / "poc" / "samples" / "培优01平面向量的概念及线性运算（含共线向量定理）（期末复习讲义）解析版.docx"
DEFAULT_OUT = ROOT / "poc" / "output" / "docx_typical_questions.md"
DEFAULT_SUMMARY = ROOT / "poc" / "output" / "docx_typical_questions_summary.json"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

EXPECTED_BY_TYPE = [
    (re.compile(r"概念|有关概念|平面向量的模"), "6.1 平面向量的概念"),
    (re.compile(r"加减法|数乘|线性运算|模的最值|取值范围"), "6.2 平面向量的线性运算"),
    (re.compile(r"共线|三点共线|基本定理"), "6.3 平面向量基本定理及坐标表示"),
]


@dataclass
class ExtractedQuestion:
    source: str
    question_type: str
    stem: str
    answer: str
    solution: str
    expected_kp: str


def extract_paragraphs(docx_path: Path) -> list[str]:
    xml = ZipFile(docx_path).read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for para in root.iter(f"{{{W_NS}}}p"):
        parts = []
        for el in para.iter():
            if el.tag in {f"{{{W_NS}}}t", f"{{{M_NS}}}t"} and el.text:
                parts.append(el.text)
        text = "".join(parts).strip()
        if text:
            paragraphs.append(re.sub(r"\s+", " ", text))
    return paragraphs


def expected_for_type(type_name: str) -> str:
    for pattern, expected in EXPECTED_BY_TYPE:
        if pattern.search(type_name):
            return expected
    return "6.2 平面向量的线性运算"


def split_stem_answer_solution(lines: list[str]) -> tuple[str, str, str]:
    answer_index = next((i for i, line in enumerate(lines) if line.startswith("【答案】")), None)
    detail_index = next((i for i, line in enumerate(lines) if line.startswith("【详解】")), None)
    if answer_index is None:
        return "\n".join(lines).strip(), "", ""
    stem = "\n".join(lines[:answer_index]).strip()
    if detail_index is None:
        answer = lines[answer_index].replace("【答案】", "", 1).strip()
        return stem, answer, ""
    answer = "\n".join(lines[answer_index:detail_index]).replace("【答案】", "", 1).strip()
    solution = "\n".join(lines[detail_index:]).replace("【详解】", "", 1).strip()
    return stem, answer, solution


def extract_questions(paragraphs: list[str]) -> tuple[list[ExtractedQuestion], dict[str, list[str]]]:
    in_typical = False
    current_type = ""
    current_notes: dict[str, list[str]] = {}
    type_notes: dict[str, list[str]] = {}
    current_block: list[str] = []
    questions: list[ExtractedQuestion] = []

    def flush_block() -> None:
        nonlocal current_block
        if not current_block or not current_type:
            current_block = []
            return
        stem, answer, solution = split_stem_answer_solution(current_block)
        label = current_block[0].split("】", 1)[0].replace("【", "") if current_block[0].startswith("【") else "题目"
        questions.append(
            ExtractedQuestion(
                source=f"{current_type}-{label}",
                question_type=current_type,
                stem=stem,
                answer=answer,
                solution=solution,
                expected_kp=expected_for_type(current_type),
            )
        )
        current_block = []

    note_label = ""
    for line in paragraphs:
        if line.startswith("期末基础通关练") or line.startswith("期末重难突破练"):
            flush_block()
            break

        if re.match(r"题型[一二三四五六七八九十]+", line):
            flush_block()
            in_typical = True
            current_type = line
            current_notes = {}
            type_notes[current_type] = []
            note_label = ""
            continue

        if not in_typical:
            continue

        if line in {"解｜题｜技｜巧", "易｜错｜点｜拨"}:
            note_label = line
            current_notes.setdefault(note_label, [])
            type_notes[current_type].append(line)
            continue

        if line.startswith("【典例") or line.startswith("【变式"):
            flush_block()
            note_label = ""
            current_block = [line]
            continue

        if current_block:
            current_block.append(line)
        elif note_label:
            current_notes.setdefault(note_label, []).append(line)
            type_notes[current_type].append(line)

    flush_block()
    return questions, type_notes


def write_questions_md(questions: list[ExtractedQuestion], out_path: Path) -> None:
    blocks = []
    for question in questions:
        blocks.append(
            "\n".join(
                [
                    f"source: {question.source}",
                    f"stem: {question.stem}",
                    f"answer: {question.answer}",
                    f"solution: {question.solution}",
                    f"expected_kp: {question.expected_kp}",
                ]
            )
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n---\n".join(blocks), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", nargs="?", type=Path, default=DEFAULT_DOCX)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()

    paragraphs = extract_paragraphs(args.docx)
    questions, type_notes = extract_questions(paragraphs)
    write_questions_md(questions, args.out)
    summary = {
        "docx": str(args.docx),
        "paragraph_count": len(paragraphs),
        "question_count": len(questions),
        "type_count": len(set(q.question_type for q in questions)),
        "question_types": {
            qtype: {
                "count": sum(1 for q in questions if q.question_type == qtype),
                "expected_kp": expected_for_type(qtype),
                "notes": type_notes.get(qtype, []),
            }
            for qtype in dict.fromkeys(q.question_type for q in questions)
        },
        "questions": [asdict(q) for q in questions],
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("paragraph_count", "question_count", "type_count")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
