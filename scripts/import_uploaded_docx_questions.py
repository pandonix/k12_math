#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from omml2latex import omml_to_latex  # noqa: E402
from wmf_render import render_wmf_batch  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "math.db"
UPLOADS = ROOT / "data" / "uploads"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
V_NS = "urn:schemas-microsoft-com:vml"
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


@dataclass
class Paragraph:
    text: str
    image_rel_ids: tuple[str, ...] = ()


@dataclass
class ParsedQuestion:
    source: str
    section: str
    label: str
    stem_md: str
    answer_md: str | None
    solution_md: str | None
    format_id: int | None
    skill: str | None = None
    pitfall: str | None = None
    tags: tuple[str, ...] = ()
    image_paths: tuple[str, ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stem_hash(stem_md: str) -> str:
    return hashlib.sha256(stem_md.strip().encode("utf-8")).hexdigest()


def extract_docx(docx_path: Path) -> tuple[list[Paragraph], dict[str, str]]:
    with ZipFile(docx_path) as docx:
        root = ET.fromstring(docx.read("word/document.xml"))
        rels = ET.fromstring(docx.read("word/_rels/document.xml.rels"))

    media_by_rel_id = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels
        if rel.attrib.get("Id") and rel.attrib.get("Target", "").startswith("media/")
    }
    shape_sizes = parse_shape_display_sizes(root)
    image_path_by_rel_id = export_all_images(docx_path, media_by_rel_id, shape_sizes)
    paragraphs: list[Paragraph] = []
    for para in root.iter(f"{{{W_NS}}}p"):
        parts: list[str] = []
        image_rel_ids: list[str] = []
        # Office Math (OMML) is structured; convert each whole equation to LaTeX
        # and skip its descendants so the inner m:t runs aren't re-emitted flat.
        omath_descendants = {
            id(node) for omath in para.iter(f"{{{M_NS}}}oMath") for node in omath.iter()
        }
        for element in para.iter():
            if element.tag == f"{{{M_NS}}}oMath":
                latex = omml_to_latex(element)
                if latex.strip():
                    parts.append(f" ${latex}$ ")
                continue
            if id(element) in omath_descendants:
                continue
            if element.tag == f"{{{W_NS}}}t" and element.text:
                parts.append(element.text)
            if element.tag == f"{{{A_NS}}}blip":
                rel_id = element.attrib.get(f"{{{R_NS}}}embed") or element.attrib.get(f"{{{R_NS}}}link")
                if rel_id:
                    image_rel_ids.append(rel_id)
                    if image_path_by_rel_id.get(rel_id):
                        parts.append(image_token(image_path_by_rel_id[rel_id]))
            if element.tag == f"{{{V_NS}}}imagedata":
                rel_id = element.attrib.get(f"{{{R_NS}}}id")
                if rel_id:
                    image_rel_ids.append(rel_id)
                    if image_path_by_rel_id.get(rel_id):
                        parts.append(image_token(image_path_by_rel_id[rel_id]))
        text = "".join(parts).strip()
        if text or image_rel_ids:
            paragraphs.append(Paragraph(re.sub(r"\s+", " ", text), tuple(dict.fromkeys(image_rel_ids))))
    return paragraphs, media_by_rel_id


def extract_paragraphs(docx_path: Path) -> list[str]:
    paragraphs, _ = extract_docx(docx_path)
    return [paragraph.text for paragraph in paragraphs if paragraph.text]


def clean_section_title(line: str) -> str:
    text = re.sub(r"\s*\d+\s*$", "", line).strip()
    text = re.sub(r"^方法技巧\s*\d+\s*", "", text).strip()
    text = re.sub(r"^易混易错\s*\d+\s*", "", text).strip()
    text = re.sub(r"^题型[一二三四五六七八九十百\d]+\s*", "", text).strip()
    return text or line.strip()


def is_method_heading(line: str) -> bool:
    return bool(re.match(r"^方法技巧\d{2}\s+", line))


def is_pitfall_heading(line: str) -> bool:
    return bool(re.match(r"^易混易错\d{2}\s*", line))


def is_question_start(line: str) -> bool:
    return bool(re.match(r"^【(?:典例|变式|跟踪训练)\d*】", line))


def question_label(line: str) -> str:
    match = re.match(r"^【([^】]+)】", line)
    return match.group(1) if match else "题目"


def split_question_block(lines: list[str]) -> tuple[str, str | None, str | None]:
    answer_index = next((i for i, line in enumerate(lines) if line.startswith("【答案】")), None)
    solution_index = next((i for i, line in enumerate(lines) if line.startswith(("【解析】", "【详解】"))), None)

    split_points = [i for i in (answer_index, solution_index) if i is not None]
    first_split = min(split_points) if split_points else len(lines)
    stem = "\n".join(lines[:first_split]).strip()

    answer = None
    if answer_index is not None:
        answer_end = solution_index if solution_index is not None and solution_index > answer_index else len(lines)
        answer = "\n".join(lines[answer_index:answer_end]).replace("【答案】", "", 1).strip() or None

    solution = None
    if solution_index is not None:
        first_line = lines[solution_index]
        label = "【解析】" if first_line.startswith("【解析】") else "【详解】"
        solution = "\n".join(lines[solution_index:]).replace(label, "", 1).strip() or None

    if answer is None and solution:
        inferred = infer_answer(solution)
        if inferred:
            answer = inferred

    return stem, answer, solution


# Display size (CSS px) for rendered equation PNGs, keyed by repo-relative path.
IMG_DISPLAY_SIZES: dict[str, tuple[int, int]] = {}


def image_token(path: str) -> str:
    size = IMG_DISPLAY_SIZES.get(path)
    if size:
        return f" [[img:{path}|{size[0]}x{size[1]}]] "
    return f" [[img:{path}]] "


def block_texts(block: list[Paragraph]) -> list[str]:
    return [paragraph.text for paragraph in block if paragraph.text]


def block_image_paths(docx_path: Path, media_by_rel_id: dict[str, str], block: list[Paragraph]) -> tuple[str, ...]:
    rel_ids = [
        rel_id
        for paragraph in block
        for rel_id in paragraph.image_rel_ids
    ]
    return export_images(docx_path, media_by_rel_id, rel_ids)


def _style_len_px(style: str, prop: str) -> int | None:
    match = re.search(rf"(?:^|;)\s*{prop}\s*:\s*([0-9.]+)(pt|px|in|cm|mm)?", style)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2) or "pt"
    factor = {"pt": 96 / 72, "px": 1.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4}[unit]
    return max(1, round(value * factor))


def parse_shape_display_sizes(root: ET.Element) -> dict[str, tuple[int, int]]:
    """Map equation rel_id -> (css_w, css_h) from the VML shape's declared size.

    Word renders MathType/OLE equation objects at the v:shape's pt size, not at
    the WMF's intrinsic extent — so this is the size they must display at.
    """
    sizes: dict[str, tuple[int, int]] = {}
    for shape in root.iter(f"{{{V_NS}}}shape"):
        style = shape.attrib.get("style", "")
        width = _style_len_px(style, "width")
        height = _style_len_px(style, "height")
        if not (width and height):
            continue
        for imagedata in shape.iter(f"{{{V_NS}}}imagedata"):
            rel_id = imagedata.attrib.get(f"{{{R_NS}}}id")
            if rel_id:
                sizes[rel_id] = (width, height)
    return sizes


def export_images(docx_path: Path, media_by_rel_id: dict[str, str], rel_ids: list[str]) -> tuple[str, ...]:
    if not rel_ids:
        return ()
    image_path_by_rel_id = export_all_images(docx_path, media_by_rel_id)
    return tuple(image_path_by_rel_id[rel_id] for rel_id in dict.fromkeys(rel_ids) if image_path_by_rel_id.get(rel_id))


_EXPORTED_IMAGE_CACHE: dict[str, dict[str, str]] = {}


def export_all_images(
    docx_path: Path,
    media_by_rel_id: dict[str, str],
    display_px_by_rel_id: dict[str, tuple[int, int]] | None = None,
) -> dict[str, str]:
    display_px_by_rel_id = display_px_by_rel_id or {}
    cache_key = str(docx_path.resolve())
    if cache_key in _EXPORTED_IMAGE_CACHE:
        return _EXPORTED_IMAGE_CACHE[cache_key]

    doc_slug = hashlib.sha1(docx_path.name.encode("utf-8")).hexdigest()[:10]
    output_dir = UPLOADS / "extracted" / doc_slug
    output_dir.mkdir(parents=True, exist_ok=True)

    exported: dict[str, str] = {}
    wmf_bytes_by_rel_id: dict[str, bytes] = {}
    with ZipFile(docx_path) as docx:
        for rel_id, target in media_by_rel_id.items():
            suffix = Path(target).suffix.lower()
            if suffix in SUPPORTED_IMAGE_SUFFIXES:
                output_path = output_dir / f"{rel_id}{suffix}"
                with output_path.open("wb") as image_file:
                    image_file.write(docx.read(f"word/{target}"))
                exported[rel_id] = str(output_path.relative_to(ROOT))
                continue
            if suffix == ".wmf":
                wmf_bytes_by_rel_id[rel_id] = docx.read(f"word/{target}")

    # MathType/legacy equations: render their WMF fallback to crisp, cropped PNGs.
    rendered = render_wmf_batch(wmf_bytes_by_rel_id, output_dir)
    for rel_id, (png_path, css_w, css_h) in rendered.items():
        rel_path = str(Path(png_path).relative_to(ROOT))
        exported[rel_id] = rel_path
        # Prefer the document's declared display size; fall back to the
        # crop-derived size only when the shape size is unavailable.
        IMG_DISPLAY_SIZES[rel_path] = display_px_by_rel_id.get(rel_id, (css_w, css_h))

    _EXPORTED_IMAGE_CACHE[cache_key] = exported
    return exported


def wmf_to_svg(data: bytes) -> str | None:
    if len(data) < 40 or data[:4] != b"\xd7\xcd\xc6\x9a":
        return None
    left, top, right, bottom = struct.unpack_from("<hhhh", data, 6)
    width = max(right - left, 1)
    height = max(bottom - top, 1)
    cursor = 22 + 18
    object_index = 0
    fonts: dict[int, dict] = {}
    selected_font = {"name": "Times New Roman", "height": -220}
    current_x = 0
    current_y = 0
    records: list[tuple[int, int, str, dict]] = []
    lines: list[tuple[int, int, int, int]] = []

    while cursor + 6 <= len(data):
        size_words = struct.unpack_from("<I", data, cursor)[0]
        function = struct.unpack_from("<H", data, cursor + 4)[0]
        payload = data[cursor + 6 : cursor + size_words * 2]
        if size_words <= 3 or function == 0:
            break

        if function == 0x02FB and len(payload) >= 50:
            height_value = struct.unpack_from("<h", payload, 0)[0]
            name = payload[18:50].split(b"\x00", 1)[0].decode("cp1252", errors="ignore") or "Times New Roman"
            fonts[object_index] = {"name": name, "height": height_value}
            object_index += 1
        elif function == 0x012D and len(payload) >= 2:
            selected_font = fonts.get(struct.unpack_from("<H", payload, 0)[0], selected_font)
        elif function == 0x0214 and len(payload) >= 4:
            current_y, current_x = struct.unpack_from("<hh", payload, 0)
        elif function == 0x0213 and len(payload) >= 4:
            next_y, next_x = struct.unpack_from("<hh", payload, 0)
            lines.append((current_x, current_y, next_x, next_y))
            current_x, current_y = next_x, next_y
        elif function == 0x0A32 and len(payload) >= 8:
            y, x, count, _options = struct.unpack_from("<hhhh", payload, 0)
            text = payload[8 : 8 + max(count, 0)].decode("cp1252", errors="ignore")
            if text:
                base_x = current_x if x == 0 else x
                base_y = current_y if y == 0 else y
                dx_start = 8 + max(count, 0) + (max(count, 0) % 2)
                if len(payload) >= dx_start + max(count, 0) * 2:
                    cursor_x = base_x
                    for char, char_width in zip(text, struct.unpack_from(f"<{count}H", payload, dx_start)):
                        records.append((cursor_x, base_y, char, dict(selected_font)))
                        cursor_x += char_width
                else:
                    records.append((base_x, base_y, text, dict(selected_font)))
        elif function == 0x0521 and len(payload) >= 6:
            count = struct.unpack_from("<H", payload, 0)[0]
            text = payload[2 : 2 + count].decode("cp1252", errors="ignore")
            if len(payload) >= 2 + count + 4:
                y, x = struct.unpack_from("<hh", payload, 2 + count)
            else:
                x, y = current_x, current_y
            if text:
                records.append((x, y, text, dict(selected_font)))

        cursor += size_words * 2

    if not records and not lines:
        return None

    formula_text = readable_formula_text(records, lines, height)
    if formula_text:
        formula_lines = wrap_formula_lines(formula_text)
        css_width = max(min(max(len(line) for line in formula_lines) * 10.5, 760), 18)
        css_height = 24 * len(formula_lines)
        tspans = "".join(
            f'<tspan x="0" y="{18 + index * 24}">{xml_escape(line)}</tspan>'
            for index, line in enumerate(formula_lines)
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {css_width:.1f} {css_height:.1f}" '
            f'width="{css_width:.1f}" height="{css_height:.1f}">'
            f'<text x="0" y="18" font-family="Arial, Helvetica, sans-serif" font-size="18">'
            f"{tspans}</text></svg>"
        )

    elements = [
        f'<line x1="{x1 - left:.1f}" y1="{y1 - top:.1f}" x2="{x2 - left:.1f}" y2="{y2 - top:.1f}" '
        'stroke="currentColor" stroke-width="18" stroke-linecap="round"/>'
        for x1, y1, x2, y2 in lines
    ]
    has_arrow = False
    for x, y, text, font in records:
        font_name = font.get("name", "Times New Roman")
        font_size = max(abs(int(font.get("height", -220))), 120)
        if is_vector_arrow(text, font_name, y, height):
            arrow_y = y - top + 18
            arrow_width = max(font_size * 0.45, 90)
            elements.append(
                f'<line x1="{x - left:.1f}" y1="{arrow_y:.1f}" '
                f'x2="{x - left + arrow_width:.1f}" y2="{arrow_y:.1f}" '
                'stroke="currentColor" stroke-width="18" stroke-linecap="round" marker-end="url(#arrow)"/>'
            )
            has_arrow = True
            continue
        elements.append(
            f'<text x="{x - left:.1f}" y="{y - top:.1f}" '
            f'font-family="{svg_font_family(font_name)}" font-size="{font_size}" '
            f'dominant-baseline="alphabetic">{xml_escape(map_wmf_text(text, font_name))}</text>'
        )

    css_width = max(width / 20, 8)
    css_height = max(height / 20, 8)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{css_width:.1f}" height="{css_height:.1f}">'
        f'{arrow_marker() if has_arrow else ""}'
        f'{"".join(elements)}</svg>'
    )


def readable_formula_text(records: list[tuple[int, int, str, dict]], lines: list[tuple[int, int, int, int]], height: int) -> str:
    text_records = split_wmf_text_records(records)
    if not text_records:
        return ""

    baseline = formula_baseline(text_records, height)
    tokens: list[dict] = []
    arrow_xs: list[int] = []

    for record in text_records:
        raw = record["text"]
        mapped = map_wmf_text(raw, record["font"])
        if is_vector_arrow(raw, record["font"], record["y"], height):
            arrow_xs.append(record["x"])
            continue
        if not mapped.strip():
            continue
        if mapped.isdigit() and record["y"] < baseline - max(height * 0.12, 70):
            mapped = mapped.translate(str.maketrans({"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}))
        tokens.append({"x": record["x"], "text": mapped, "kind": "text", "vector": False})

    for x1, y1, x2, y2 in lines:
        if abs(x1 - x2) <= 35 and abs(y2 - y1) >= height * 0.45:
            tokens.append({"x": x1, "text": "|", "kind": "bar"})

    for arrow_x in arrow_xs:
        candidates = [
            token for token in tokens
            if token["kind"] == "text" and re.match(r"[A-Za-z]", token["text"]) and abs(token["x"] - arrow_x) <= 220
        ]
        if candidates:
            target = min(candidates, key=lambda token: abs(token["x"] - arrow_x))
            if not target.get("vector"):
                target["text"] = f"vec({target['text']})"
                target["vector"] = True

    formula = "".join(token["text"] for token in sorted(tokens, key=lambda token: token["x"]))
    return normalize_formula_text(formula)


def split_wmf_text_records(records: list[tuple[int, int, str, dict]]) -> list[dict]:
    split_records: list[dict] = []
    for x, y, text, font in records:
        width = max(abs(int(font.get("height", -220))) * 0.52, 90)
        for index, char in enumerate(text):
            split_records.append({"x": x + int(index * width), "y": y, "text": char, "font": font.get("name", "Times New Roman")})
    return split_records


def formula_baseline(records: list[dict], height: int) -> int:
    ys = [
        record["y"] for record in records
        if not is_vector_arrow(record["text"], record["font"], record["y"], height)
    ]
    if not ys:
        return int(height * 0.75)
    return sorted(ys)[len(ys) // 2]


def normalize_formula_text(text: str) -> str:
    text = text.replace("cos,", "cos")
    text = re.sub(r"vec\(([A-Za-z])\),π\]vec\(([A-Za-z])\)∈\[0,", r"angle(vec(\1),vec(\2))∈[0,π]", text)
    text = re.sub(r"cos(vec\([A-Za-z]\)),(vec\([A-Za-z]\))", r"cos(\1,\2)", text)
    return text.strip()


def wrap_formula_lines(text: str, max_chars: int = 46) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    lines: list[str] = []
    rest = text
    break_chars = "=≤≥<>，,；;+"
    while len(rest) > max_chars:
        break_at = -1
        for index in range(min(max_chars, len(rest) - 1), max(18, max_chars // 2), -1):
            if rest[index] in break_chars:
                break_at = index + 1
                break
        if break_at < 0:
            for index in range(min(max_chars, len(rest) - 1), max(18, max_chars // 2), -1):
                if rest[index] in "-·":
                    break_at = index
                    break
        if break_at < 0:
            break_at = max_chars
        lines.append(rest[:break_at])
        rest = rest[break_at:]
    if rest:
        lines.append(rest)
    return lines


def is_vector_arrow(text: str, font_name: str, y: int, height: int) -> bool:
    if text != "r":
        return False
    if "MT Extra" in font_name or "Symbol" in font_name:
        return True
    return y < height * 0.45


def arrow_marker() -> str:
    return (
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L8,4 L0,8 Z" fill="currentColor"/></marker></defs>'
    )


def map_wmf_text(text: str, font_name: str) -> str:
    if "MT Extra" in font_name or "Symbol" in font_name:
        return text.translate(str.maketrans({"£": "≤", "Î": "∈", "ð": "π", "^": "⊥", "×": "·"}))
    return text.translate(str.maketrans({"£": "≤", "Î": "∈", "ð": "π", "^": "⊥", "×": "·"}))


def svg_font_family(font_name: str) -> str:
    if "Symbol" in font_name or "MT Extra" in font_name:
        return "Times New Roman, serif"
    return f"{xml_escape(font_name)}, Times New Roman, serif"


def xml_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def infer_answer(solution: str) -> str | None:
    choice = re.search(r"故选[:：]?\s*([A-D])", solution)
    if choice:
        return choice.group(1)
    fill = re.search(r"故答案为[:：]\s*([^。\n]+)", solution)
    if fill:
        return fill.group(1).strip()
    return None


def infer_format_id(stem: str, answer: str | None) -> int | None:
    if re.search(r"A[．.、].*B[．.、]", stem):
        return 1
    if "（ ）" in stem or "( )" in stem or (answer and re.fullmatch(r"[A-D]", answer.strip())):
        return 1
    if "____" in stem or "________" in stem or "填空" in stem:
        return 2
    if "证明" in stem:
        return 4
    return 3


def parse_method_doc(docx_path: Path) -> list[ParsedQuestion]:
    paragraphs, media_by_rel_id = extract_docx(docx_path)
    questions: list[ParsedQuestion] = []
    section = ""
    current: list[Paragraph] = []

    def flush() -> None:
        nonlocal current
        if not current or not section:
            current = []
            return
        lines = block_texts(current)
        stem, answer, solution = split_question_block(lines)
        if stem:
            skill = clean_section_title(section)
            label = question_label(lines[0])
            questions.append(
                ParsedQuestion(
                    source=f"{docx_path.stem}｜{skill}｜{label}",
                    section=skill,
                    label=label,
                    stem_md=stem,
                    answer_md=answer,
                    solution_md=solution,
                    format_id=infer_format_id(stem, answer),
                    skill=skill,
                    tags=("docx导入", "方法技巧", "高一数学"),
                    image_paths=block_image_paths(docx_path, media_by_rel_id, current),
                )
            )
        current = []

    for paragraph in paragraphs:
        line = paragraph.text
        if is_method_heading(line):
            flush()
            section = clean_section_title(line)
            continue
        if is_pitfall_heading(line):
            flush()
            section = ""
            continue
        if is_question_start(line):
            flush()
            current = [paragraph]
            continue
        if current:
            current.append(paragraph)
    flush()
    return questions


def parse_pitfall_doc(docx_path: Path) -> list[ParsedQuestion]:
    paragraphs, media_by_rel_id = extract_docx(docx_path)
    questions: list[ParsedQuestion] = []
    section = ""
    current: list[Paragraph] = []

    def flush() -> None:
        nonlocal current
        if not current or not section:
            current = []
            return
        lines = block_texts(current)
        stem, answer, solution = split_question_block(lines)
        if stem:
            pitfall = clean_section_title(section)
            label = question_label(lines[0])
            questions.append(
                ParsedQuestion(
                    source=f"{docx_path.stem}｜{pitfall}｜{label}",
                    section=pitfall,
                    label=label,
                    stem_md=stem,
                    answer_md=answer,
                    solution_md=solution,
                    format_id=infer_format_id(stem, answer),
                    pitfall=pitfall,
                    tags=("docx导入", "易混易错", "高一下学期"),
                    image_paths=block_image_paths(docx_path, media_by_rel_id, current),
                )
            )
        current = []

    for paragraph in paragraphs:
        line = paragraph.text
        if is_pitfall_heading(line):
            flush()
            section = clean_section_title(line)
            continue
        if is_method_heading(line):
            flush()
            section = ""
            continue
        if is_question_start(line):
            flush()
            current = [paragraph]
            continue
        if current:
            current.append(paragraph)
    flush()
    return questions


def load_knowledge_points(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT id, title, chapter, section, content_md
        FROM knowledge_points
        ORDER BY order_index
        """
    ).fetchall()


def kp_candidates(question: ParsedQuestion, kps: list[sqlite3.Row], limit: int = 3) -> list[tuple[str, float]]:
    text = f"{question.section}\n{question.stem_md}\n{question.solution_md or ''}"
    manual = manual_kp_ids(text)
    if manual:
        return [(kp_id, 1.0 if index == 0 else 0.75) for index, kp_id in enumerate(manual[:limit])]

    scored: list[tuple[str, float]] = []
    for kp in kps:
        corpus = f"{kp['title']} {kp['chapter'] or ''} {kp['section'] or ''} {kp['content_md'] or ''}"
        score = 0.0
        for token in extract_terms(text):
            if token in corpus:
                score += min(len(token), 8) / 8
        if kp["title"] in text or (kp["section"] and kp["section"] in text):
            score += 3
        if score >= 2:
            scored.append((kp["id"], round(min(score / 8, 1.0), 3)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def manual_kp_ids(text: str) -> list[str]:
    rules = [
        (r"诱导公式", ["k-6atcja"]),
        (r"终边|任意角|弧度", ["k-fugtur", "k-louy5x"]),
        (r"三角函数.*(概念|定义)", ["k-louy5x"]),
        (r"单调|函数图象|图象变换|对称轴|参数问题|五点", ["k-ytcddl", "k-kg9iva"]),
        (r"恒等|和差|正切公式", ["k-f83goj"]),
        (r"正.?余弦定理|解三角形|边角互化|三角形.*面积|测量距离|测量高度|解的个数", ["k-e7njc6"]),
        (r"平面向量的概念|零向量|单位向量|共线向量", ["k-3ygqtc"]),
        (r"线性运算|加减法|数乘", ["k-qhiyx0"]),
        (r"向量共线|基本定理|坐标运算|坐标表示", ["k-pmsa2q"]),
        (r"数量积|夹角", ["k-j0q7ev"]),
        (r"向量.*应用|几何中的应用", ["k-kj8kr5"]),
        (r"复数.*(概念|实部|虚部|共轭)", ["k-w75t81"]),
        (r"复数.*几何意义", ["k-obnlwo"]),
        (r"复数.*(运算|四则)", ["k-evj0s2"]),
        (r"复数.*三角", ["k-n4vfek"]),
        (r"斜二测|直观图", ["k-9rrcr1"]),
        (r"外接球|内切球|棱切球|球心", ["k-kgrl9m"]),
        (r"线面位置|异面直线", ["k-gunwfi"]),
        (r"平行", ["k-aq46wv"]),
        (r"垂直", ["k-6but60"]),
        (r"古典概型", ["k-jh50zo"]),
        (r"有放回|不放回|样本点|列举|随机模拟", ["k-jh50zo"]),
        (r"互斥|对立|相互独立|独立事件", ["k-7c2awq", "k-tkxquc"]),
        (r"概率|随机事件", ["k-tkxquc"]),
        (r"随机抽样", ["k-f8rxf4"]),
        (r"统计图表|中位数|百分位数|频率分布|总体|样本|集中趋势|离散程度|方差", ["k-w93oaf"]),
    ]
    for pattern, ids in rules:
        if re.search(pattern, text):
            return ids
    return []


def extract_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for part in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text):
        if len(part) < 2:
            continue
        if len(part) <= 8:
            terms.add(part)
        for size in (2, 3, 4, 5, 6):
            for index in range(0, max(len(part) - size + 1, 0)):
                terms.add(part[index : index + size])
    return terms


def upsert_named_node(conn: sqlite3.Connection, table: str, name: str, content_col: str, source: str | None = None) -> int:
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row[0])
    now = utc_now()
    if table == "question_patterns":
        cursor = conn.execute(
            "INSERT INTO question_patterns(name, strategy_md, source, order_index, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?)",
            (name, None, source, now, now),
        )
    else:
        cursor = conn.execute(
            f"INSERT INTO {table}(name, {content_col}, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, None, now, now),
        )
    return int(cursor.lastrowid)


def import_questions(conn: sqlite3.Connection, questions: list[ParsedQuestion]) -> dict:
    kps = load_knowledge_points(conn)
    cleanup_source_duplicates(conn, [question.source for question in questions])
    cleanup_stale_docx_questions(conn, [question.source for question in questions])
    inserted = 0
    reused = 0
    question_ids: list[int] = []
    now = utc_now()

    for question in questions:
        q_hash = stem_hash(question.stem_md)
        row = conn.execute(
            """
            SELECT q.id
            FROM questions q
            WHERE q.source = ?
              AND EXISTS (
                SELECT 1 FROM question_tags qt
                WHERE qt.question_id = q.id AND qt.tag = 'docx导入'
              )
            ORDER BY q.id DESC
            LIMIT 1
            """,
            (question.source,),
        ).fetchone()
        if row is None:
            row = conn.execute("SELECT id FROM questions WHERE hash = ?", (q_hash,)).fetchone()
        existing_docx_question = False
        if row:
            question_id = int(row[0])
            reused += 1
            existing_docx_question = should_replace_edges(conn, question_id)
            if existing_docx_question:
                conn.execute(
                    """
                    UPDATE questions
                    SET source = ?,
                        format_id = ?,
                        difficulty = ?,
                        stem_md = ?,
                        answer_md = ?,
                        solution_md = ?,
                        image_path = ?,
                        hash = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        question.source,
                        question.format_id,
                        3,
                        question.stem_md,
                        question.answer_md,
                        question.solution_md,
                        image_path_value(question.image_paths),
                        q_hash,
                        now,
                        question_id,
                    ),
                )
        else:
            cursor = conn.execute(
                """
                INSERT INTO questions(
                  source, format_id, difficulty, stem_md, options_json, answer_key_json,
                  answer_md, solution_md, image_path, hash, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question.source,
                    question.format_id,
                    3,
                    question.stem_md,
                    question.answer_md,
                    question.solution_md,
                    image_path_value(question.image_paths),
                    q_hash,
                    now,
                    now,
                ),
            )
            question_id = int(cursor.lastrowid)
            inserted += 1

        question_ids.append(question_id)
        if row and not existing_docx_question:
            continue
        if existing_docx_question:
            clear_question_edges(conn, question_id)
        attach_edges(conn, question_id, question, kps)

    sync_pattern_edges_from_question_edges(conn)
    return {
        "parsed": len(questions),
        "inserted": inserted,
        "reused": reused,
        "question_ids": question_ids,
    }


def sync_pattern_edges_from_question_edges(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM pattern_skills")
    conn.execute("DELETE FROM pattern_pitfalls")
    conn.execute(
        """
        INSERT INTO pattern_skills(pattern_id, skill_id, weight)
        SELECT qpm.pattern_id,
               qs.skill_id,
               MAX(COALESCE(qpm.weight, 1.0) * COALESCE(qs.weight, 1.0)) AS weight
        FROM question_patterns_map qpm
        JOIN question_skills qs ON qs.question_id = qpm.question_id
        GROUP BY qpm.pattern_id, qs.skill_id
        """
    )
    conn.execute(
        """
        INSERT INTO pattern_pitfalls(pattern_id, pitfall_id, weight)
        SELECT qpm.pattern_id,
               qp.pitfall_id,
               MAX(COALESCE(qpm.weight, 1.0) * COALESCE(qp.weight, 1.0)) AS weight
        FROM question_patterns_map qpm
        JOIN question_pitfalls qp ON qp.question_id = qpm.question_id
        GROUP BY qpm.pattern_id, qp.pitfall_id
        """
    )


def cleanup_source_duplicates(conn: sqlite3.Connection, sources: list[str]) -> None:
    for source in dict.fromkeys(sources):
        rows = conn.execute(
            """
            SELECT q.id
            FROM questions q
            WHERE q.source = ?
              AND EXISTS (
                SELECT 1 FROM question_tags qt
                WHERE qt.question_id = q.id AND qt.tag = 'docx导入'
              )
            ORDER BY q.id DESC
            """,
            (source,),
        ).fetchall()
        for row in rows[1:]:
            conn.execute("DELETE FROM questions WHERE id = ?", (int(row[0]),))


def cleanup_stale_docx_questions(conn: sqlite3.Connection, sources: list[str]) -> None:
    current = set(sources)
    rows = conn.execute(
        """
        SELECT q.id, q.source
        FROM questions q
        WHERE EXISTS (
          SELECT 1 FROM question_tags qt
          WHERE qt.question_id = q.id AND qt.tag = 'docx导入'
        )
          AND (
            q.source LIKE '高一数学62个方法技巧全归纳%'
            OR q.source LIKE '高一下学期数学26个易混易错全归纳%'
          )
        """
    ).fetchall()
    for row in rows:
        if row[1] not in current:
            conn.execute("DELETE FROM questions WHERE id = ?", (int(row[0]),))


def image_path_value(image_paths: tuple[str, ...]) -> str | None:
    if not image_paths:
        return None
    if len(image_paths) == 1:
        return image_paths[0]
    return json.dumps(list(image_paths), ensure_ascii=False)


def should_replace_edges(conn: sqlite3.Connection, question_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM question_tags WHERE question_id = ? AND tag = 'docx导入'",
        (question_id,),
    ).fetchone()
    return row is not None


def clear_question_edges(conn: sqlite3.Connection, question_id: int) -> None:
    for table in ("question_kp", "question_patterns_map", "question_skills", "question_pitfalls", "question_tags"):
        conn.execute(f"DELETE FROM {table} WHERE question_id = ?", (question_id,))


def attach_edges(
    conn: sqlite3.Connection,
    question_id: int,
    question: ParsedQuestion,
    kps: list[sqlite3.Row],
) -> None:
    candidates = kp_candidates(question, kps)
    for index, (kp_id, weight) in enumerate(candidates):
        conn.execute(
            "INSERT OR REPLACE INTO question_kp(question_id, kp_id, weight, is_primary) VALUES (?, ?, ?, ?)",
            (question_id, kp_id, weight, 1 if index == 0 else 0),
        )

    if question.skill:
        skill_id = upsert_named_node(conn, "skills", question.skill, "content_md")
        conn.execute(
            "INSERT OR REPLACE INTO question_skills(question_id, skill_id, weight) VALUES (?, ?, ?)",
            (question_id, skill_id, 1.0),
        )

    if question.pitfall:
        pitfall_id = upsert_named_node(conn, "common_pitfalls", question.pitfall, "content_md")
        conn.execute(
            "INSERT OR REPLACE INTO question_pitfalls(question_id, pitfall_id, weight) VALUES (?, ?, ?)",
            (question_id, pitfall_id, 1.0),
        )

    # The two source docs are 方法技巧 / 易混易错 collections: the section *is*
    # the skill / pitfall (already linked above), not a 题型. Only materialise a
    # question_pattern when the section is a genuine 题型 (neither skill nor
    # pitfall). See PLAN §3.1/§5.1 — these node types are mutually exclusive.
    if not question.skill and not question.pitfall:
        pattern_id = upsert_named_node(conn, "question_patterns", question.section, "strategy_md", source="docx_import")
        conn.execute(
            "INSERT OR REPLACE INTO question_patterns_map(question_id, pattern_id, weight, is_primary) VALUES (?, ?, ?, ?)",
            (question_id, pattern_id, 1.0, 1),
        )

    for tag in question.tags:
        conn.execute(
            "INSERT OR IGNORE INTO question_tags(question_id, tag) VALUES (?, ?)",
            (question_id, tag),
        )


def backup_db(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.name}.before-docx-import.{stamp}.bak")
    shutil.copy2(db_path, backup_path)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Import uploaded method/pitfall DOCX question banks into SQLite.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    method_doc = UPLOADS / "高一数学62个方法技巧全归纳（解析版）.docx"
    pitfall_doc = UPLOADS / "高一下学期数学26个易混易错全归纳（解析版）.docx"
    questions = parse_method_doc(method_doc) + parse_pitfall_doc(pitfall_doc)

    if args.dry_run:
        print(json.dumps({"parsed": len(questions), "sample_sources": [q.source for q in questions[:5]]}, ensure_ascii=False, indent=2))
        return

    backup = backup_db(args.db)
    with sqlite3.connect(args.db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        result = import_questions(conn, questions)
        conn.commit()

    result["backup"] = str(backup) if backup else None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
