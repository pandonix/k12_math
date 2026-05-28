#!/usr/bin/env python3
"""M0 knowledge-graph proof of concept.

This script intentionally uses only the Python standard library. It answers:
1. Can the existing knowledge markdown be converted into structured rows?
2. Can sample questions be associated with the current knowledge graph shape?
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MD = ROOT / "高一数学知识点总整理（人教A版必修一二详版）.md"
DEFAULT_QUESTIONS = ROOT / "poc" / "samples" / "sample_questions.md"
DEFAULT_OUT = ROOT / "poc" / "output"

MATH_TERMS = {
    "集合", "元素", "互异性", "子集", "真子集", "空集", "交集", "并集", "补集", "全集",
    "充分条件", "必要条件", "充要条件", "全称量词", "存在量词", "命题", "否定",
    "不等式", "二次函数", "一元二次", "判别式", "根与系数", "基本不等式",
    "函数", "定义域", "值域", "单调性", "单调", "递增", "递减", "奇偶性", "最大值", "最小值", "零点",
    "指数", "指数函数", "对数", "对数函数", "幂函数", "换底公式", "图象", "图像",
    "三角函数", "诱导公式", "同角三角", "正弦", "余弦", "正切", "周期", "振幅",
    "向量", "平面向量", "共线向量", "共线定理", "三点共线", "线性运算", "加法", "减法", "数乘",
    "模", "单位向量", "零向量", "相等向量", "相反向量", "数量积", "夹角", "坐标运算", "解三角形", "正弦定理", "余弦定理",
    "复数", "虚部", "实部", "模", "共轭复数",
    "直线", "平面", "垂直", "平行", "立体几何", "棱柱", "棱锥", "球", "体积", "表面积",
    "统计", "样本", "平均数", "方差", "标准差", "频率", "百分位数",
    "概率", "随机事件", "古典概型", "互斥事件", "独立事件",
}

STOP_TERMS = {
    "若", "则", "且", "或", "已知", "求", "判断", "证明", "下列", "关于", "其中",
    "一个", "两个", "以及", "满足", "条件", "问题", "结果", "方法", "性质", "公式",
    "核心", "概念", "高频", "考点", "提醒", "典型", "题型", "入口",
}


@dataclass
class KnowledgePoint:
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


@dataclass
class Question:
    source: str
    stem_md: str
    answer_md: str = ""
    solution_md: str = ""
    expected_kp: str = ""


@dataclass
class Association:
    question_source: str
    stem_md: str
    expected_kp: str
    top_matches: list[dict]
    confidence: str


def js_int32(value: int) -> int:
    value &= 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value


def base36(value: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    out = []
    while value:
        value, rem = divmod(value, 36)
        out.append(chars[rem])
    return "".join(reversed(out))


def slugify_js(text: str) -> str:
    hash_value = 0
    for char in text:
        hash_value = js_int32(js_int32(hash_value << 5) - hash_value + ord(char))
    return f"k-{base36(abs(hash_value))}"


def strip_markdown(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"\$\$([\s\S]*?)\$\$", r" \1 ", text)
    text = re.sub(r"[#>*_|`\[\](){}\\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def infer_tags(title: str, content: str) -> list[str]:
    text = f"{title}\n{content}"
    tags = []
    if re.search(r"\$\$|公式|定理|恒等式|运算律|坐标公式|面积公式|体积|表面积|半径", text):
        tags.append("公式")
    if re.search(r"高频考点|典型题型|常用思路", text):
        tags.append("考点")
    if re.search(r"易错提醒|易错点", text):
        tags.append("易错")
    if "二级结论" in text:
        tags.append("二级结论")
    return tags


def extract_facets(content: str) -> list[str]:
    return [m.group(2).strip() for m in re.finditer(r"^(#{4})\s+(.+)$", content, re.M)]


def parse_knowledge_markdown(markdown: str) -> list[KnowledgePoint]:
    lines = markdown.replace("\r\n", "\n").split("\n")
    items: list[KnowledgePoint] = []
    book = ""
    chapter = ""
    current: dict | None = None

    def push_current() -> None:
        nonlocal current
        if not current:
            return
        content = "\n".join(current["lines"]).strip()
        title = re.sub(r"\s+", " ", current["title"]).strip()
        order_index = len(items)
        legacy_formula = f"{current['book']}-{current['chapter']}-{current['raw_title']}-{order_index}"
        item_id = slugify_js(legacy_formula)
        items.append(
            KnowledgePoint(
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


def cjk_ngrams(text: str) -> Iterable[str]:
    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        for n in (2, 3, 4):
            if len(seq) >= n:
                for i in range(len(seq) - n + 1):
                    yield seq[i : i + n]


def tokenize(text: str) -> Counter[str]:
    normalized = strip_markdown(text).lower()
    terms: Counter[str] = Counter()
    for term in MATH_TERMS:
        if term in normalized:
            terms[term] += 4
    for token in re.findall(r"[a-zA-Z]+|\\[a-zA-Z]+|\d+\.\d+|\d+", text):
        if len(token) > 1:
            terms[token.lower().lstrip("\\")] += 1
    for token in cjk_ngrams(normalized):
        if token not in STOP_TERMS:
            terms[token] += 1
    raw = text.lower()
    if "\\log" in raw or "log" in raw:
        terms["对数"] += 8
        terms["对数函数"] += 4
    if "\\sin" in raw or "\\cos" in raw or "\\tan" in raw or "sin" in raw or "cos" in raw or "tan" in raw:
        terms["三角函数"] += 6
    if "\\sin" in raw or "sin" in raw:
        terms["正弦"] += 4
    if "\\cos" in raw or "cos" in raw:
        terms["余弦"] += 4
    if "\\tan" in raw or "tan" in raw:
        terms["正切"] += 4
    if "\\vec" in raw:
        terms["向量"] += 8
    if "\\cdot" in raw or "·" in raw:
        terms["数量积"] += 8
    if "\\sqrt" in raw or "分母" in normalized:
        terms["定义域"] += 4
    if "^2" in raw and ("\\le" in raw or "\\ge" in raw or "<" in raw or ">" in raw):
        terms["一元二次"] += 5
        terms["不等式"] += 4
    return terms


def build_kp_index(items: list[KnowledgePoint]) -> dict[str, Counter[str]]:
    index = {}
    for kp in items:
        title_terms = tokenize(f"{kp.chapter} {kp.section} {kp.title}")
        content_terms = tokenize(kp.content_md)
        terms = Counter()
        for term, count in content_terms.items():
            terms[term] += min(count, 4)
        for term, count in title_terms.items():
            terms[term] += count * 4
        for tag in kp.tags:
            terms[tag] += 3
        for facet in kp.facets:
            for term, count in tokenize(facet).items():
                terms[term] += count * 2
        index[kp.id] = terms
    return index


def normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", strip_markdown(text)).lower()


def parse_questions(path: Path) -> list[Question]:
    text = path.read_text(encoding="utf-8")
    blocks = [block.strip() for block in re.split(r"\n---+\n", text) if block.strip()]
    questions = []
    for index, block in enumerate(blocks, 1):
        fields = {"source": f"样例题-{index}", "stem": "", "answer": "", "solution": "", "expected_kp": ""}
        current_key = None
        for line in block.splitlines():
            m = re.match(r"^(source|stem|answer|solution|expected_kp)\s*:\s*(.*)$", line, re.I)
            if m:
                current_key = m.group(1).lower()
                fields[current_key] = m.group(2).strip()
                continue
            if current_key:
                fields[current_key] = f"{fields[current_key]}\n{line}".strip()
        if fields["stem"]:
            questions.append(
                Question(
                    source=fields["source"],
                    stem_md=fields["stem"],
                    answer_md=fields["answer"],
                    solution_md=fields["solution"],
                    expected_kp=fields["expected_kp"],
                )
            )
    return questions


def score_question(question: Question, kp: KnowledgePoint, kp_terms: Counter[str], idf: dict[str, float]) -> float:
    q_terms = tokenize(f"{question.stem_md}\n{question.answer_md}\n{question.solution_md}")
    if not q_terms:
        return 0.0
    raw = 0.0
    for term, q_count in q_terms.items():
        raw += min(q_count, 3) * kp_terms.get(term, 0) * idf.get(term, 1.0)
    length_penalty = math.sqrt(max(1, sum(kp_terms.values())))
    title_bonus = 0.0
    question_text = strip_markdown(question.stem_md)
    if kp.title and kp.title in question_text:
        title_bonus += 12.0
    if kp.chapter and any(term in question_text for term in tokenize(kp.chapter)):
        title_bonus += 2.0
    kp_text = normalize_for_match(f"{kp.title} {kp.content_md}")
    for term in MATH_TERMS:
        if term in question_text and term in kp_text:
            title_bonus += 3.0
    score = (raw / length_penalty) + title_bonus
    if kp.book == "附录" and kp.level == 2:
        score *= 0.72
    return round(score, 4)


def associate_questions(items: list[KnowledgePoint], questions: list[Question]) -> list[Association]:
    kp_index = build_kp_index(items)
    document_frequency = Counter(term for terms in kp_index.values() for term in terms)
    idf = {
        term: math.log((len(items) + 1) / (frequency + 1)) + 1
        for term, frequency in document_frequency.items()
    }
    associations = []
    for question in questions:
        scored = []
        for kp in items:
            score = score_question(question, kp, kp_index[kp.id], idf)
            if score > 0:
                scored.append((score, kp))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:5]
        if not top:
            confidence = "none"
        else:
            first = top[0][0]
            second = top[1][0] if len(top) > 1 else 0
            confidence = "high" if first >= 18 and first >= second * 1.25 else "medium" if first >= 9 else "low"
        associations.append(
            Association(
                question_source=question.source,
                stem_md=question.stem_md,
                expected_kp=question.expected_kp,
                top_matches=[
                    {
                        "rank": rank,
                        "score": score,
                        "kp_id": kp.id,
                        "book": kp.book,
                        "chapter": kp.chapter,
                        "section": kp.section,
                        "tags": kp.tags,
                        "expected_hit": bool(
                            question.expected_kp
                            and (
                                question.expected_kp in {kp.id, kp.section, kp.title}
                                or normalize_for_match(question.expected_kp) in normalize_for_match(f"{kp.section} {kp.title}")
                                or normalize_for_match(kp.section) in normalize_for_match(question.expected_kp)
                            )
                        ),
                    }
                    for rank, (score, kp) in enumerate(top, 1)
                ],
                confidence=confidence,
            )
        )
    return associations


def summarize(items: list[KnowledgePoint], associations: list[Association], md_path: Path, question_path: Path) -> dict:
    chapter_counts = Counter((item.book, item.chapter) for item in items)
    tag_counts = Counter(tag for item in items for tag in item.tags)
    level_counts = Counter(str(item.level) for item in items)
    duplicate_ids = [kp_id for kp_id, count in Counter(item.id for item in items).items() if count > 1]
    expected_total = sum(
        1
        for assoc in associations
        if assoc.expected_kp
        and any(match["expected_hit"] for match in assoc.top_matches[:3])
    )
    with_expectation = sum(1 for assoc in associations if assoc.expected_kp)
    confidence_counts = Counter(assoc.confidence for assoc in associations)
    return {
        "inputs": {
            "knowledge_md": str(md_path),
            "questions": str(question_path),
        },
        "knowledge_points": {
            "count": len(items),
            "books": sorted(set(item.book for item in items if item.book)),
            "chapters": len(chapter_counts),
            "level_counts": dict(level_counts),
            "tag_counts": dict(tag_counts),
            "with_facets": sum(1 for item in items if item.facets),
            "duplicate_ids": duplicate_ids,
        },
        "association": {
            "question_count": len(associations),
            "confidence_counts": dict(confidence_counts),
            "expected_top3_hits": expected_total,
            "expected_top3_hit_rate": round(expected_total / with_expectation, 4) if with_expectation else None,
        },
    }


def write_report(out_dir: Path, summary: dict, associations: list[Association]) -> None:
    lines = [
        "# M0 知识图谱 POC 报告",
        "",
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 1. 知识点 md 结构化结果",
        "",
        f"- 知识点行数：{summary['knowledge_points']['count']}",
        f"- 覆盖册别：{', '.join(summary['knowledge_points']['books'])}",
        f"- 章节组合数：{summary['knowledge_points']['chapters']}",
        f"- 层级分布：{summary['knowledge_points']['level_counts']}",
        f"- 标签分布：{summary['knowledge_points']['tag_counts']}",
        f"- 含四级小标题 facets 的知识点：{summary['knowledge_points']['with_facets']}",
        f"- 重复 ID：{len(summary['knowledge_points']['duplicate_ids'])}",
        "",
        "结论：现有 md 可以稳定转成 M0 需要的 `knowledge_points` 行。为兼容当前前端，POC 按现有 `app.js` 逻辑把 `###` 作为知识点卡片，`####` 保留在 `content_md` 中并额外抽取为 `facets` 辅助检索。",
        "",
        "## 2. 题目关联 POC 结果",
        "",
        f"- 题目数：{summary['association']['question_count']}",
        f"- 置信度分布：{summary['association']['confidence_counts']}",
        f"- 带预期知识点样例的 Top3 命中率：{summary['association']['expected_top3_hit_rate']}",
        "",
        "| 题目 | 置信度 | Top1 知识点 | 分数 | Top3 |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for assoc in associations:
        top1 = assoc.top_matches[0] if assoc.top_matches else {}
        top3 = "；".join(match["section"] for match in assoc.top_matches[:3])
        lines.append(
            f"| {assoc.question_source} | {assoc.confidence} | {top1.get('section', '')} | {top1.get('score', 0)} | {top3} |"
        )
    lines.extend(
        [
            "",
            "## 3. 对当前设计的判断",
            "",
            "- `knowledge_points` 主表足够承载第一阶段：`book/chapter/section/title/content_md/tags/order_index` 都能从 md 直接生成。",
            "- `parent_id` 在兼容现有 UI 的模式下暂时没有天然父节点；建议 M0 先置空，用 `book/chapter/section` 建树。若后续要把四级标题也作为可训练节点，再补 `kp_facets` 或 graph node 表。",
            "- 题目关联可以先用规则召回做候选集，再让人工或 LLM 精排。纯规则已经能做可解释的 Top-K，但相近知识点仍会混淆。",
            "- 当前报告基于 `inputs.questions` 指向的题目样本；若该样本来自真实试卷、讲义或 OCR 转写，可直接作为真实材料验证结果解读。",
            "",
        ]
    )
    (out_dir / "poc_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    markdown = args.knowledge_md.read_text(encoding="utf-8")
    items = parse_knowledge_markdown(markdown)
    questions = parse_questions(args.questions)
    associations = associate_questions(items, questions)
    summary = summarize(items, associations, args.knowledge_md, args.questions)

    (args.out / "knowledge_points.json").write_text(
        json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out / "question_associations.json").write_text(
        json.dumps([asdict(item) for item in associations], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(args.out, summary, associations)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
