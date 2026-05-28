from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from backend.schemas import ParsedLearningMaterial, ParsedQuestionPreview


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOCX = PROJECT_ROOT / "poc" / "samples" / "培优01平面向量的概念及线性运算（含共线向量定理）（期末复习讲义）解析版.docx"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


EXPECTED_BY_TYPE = [
    (re.compile(r"概念|有关概念|平面向量的模"), "6.1 平面向量的概念"),
    (re.compile(r"加减法|数乘|线性运算|模的最值|取值范围"), "6.2 平面向量的线性运算"),
    (re.compile(r"共线|三点共线|基本定理"), "6.3 平面向量基本定理及坐标表示"),
]


@dataclass(frozen=True)
class ExtractedQuestion:
    source: str
    question_type: str
    stem: str
    answer: str
    solution: str
    expected_kp: str


def import_docx_handout(docx_path: Path = DEFAULT_DOCX) -> ParsedLearningMaterial:
    paragraphs = extract_paragraphs(docx_path)
    questions, type_notes = extract_questions(paragraphs)
    patterns = [
        {
            "name": qtype,
            "expected_kp": expected_for_type(qtype),
            "notes": notes,
            "question_count": sum(1 for question in questions if question.question_type == qtype),
        }
        for qtype, notes in type_notes.items()
    ]
    return ParsedLearningMaterial(
        source_path=str(docx_path),
        paragraph_count=len(paragraphs),
        type_count=len(patterns),
        question_count=len(questions),
        patterns=patterns,
        questions=[
            ParsedQuestionPreview(
                source=question.source,
                question_type=question.question_type,
                stem=question.stem,
                answer=question.answer,
                solution=question.solution,
                expected_kp=question.expected_kp,
            )
            for question in questions
        ],
    )


def extract_paragraphs(docx_path: Path) -> list[str]:
    xml = ZipFile(docx_path).read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs: list[str] = []
    for para in root.iter(f"{{{W_NS}}}p"):
        parts: list[str] = []
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
    note_label = ""
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

    for line in paragraphs:
        if line.startswith("期末基础通关练") or line.startswith("期末重难突破练"):
            flush_block()
            break
        if re.match(r"题型[一二三四五六七八九十]+", line):
            flush_block()
            in_typical = True
            current_type = line
            type_notes.setdefault(current_type, [])
            note_label = ""
            continue
        if not in_typical:
            continue
        if line in {"解｜题｜技｜巧", "易｜错｜点｜拨"}:
            note_label = line
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
            type_notes[current_type].append(line)

    flush_block()
    return questions, type_notes
