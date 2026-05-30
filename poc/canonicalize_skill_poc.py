#!/usr/bin/env python3
"""
最小验证：跨来源「技巧」语义归一 (concept-card 抽取 + LLM 判同)

目标：把同一个数学技巧「极化恒等式」在两份不同系列讲义里的不同描述，
合并成 *一个* canonical 技巧节点（带 aliases / 统一公式 / 两边证据）。

样本（真实素材，均在 20260530/03_平面向量/ 下）：
  A = 专题2.3 平面向量中极化恒等式及常见公式应用 解析版.docx
  B = 培优06 拓展专题之二：巧用极化恒等式解决平面向量问题（期末复习讲义）（解析版）.docx

流程：
  1) 从两份 docx 抽出与「极化恒等式」相关的正文片段（确定性，无 LLM）
  2) LLM 调用 ×2：把每份片段抽成结构化「概念卡」(tool use 强制 JSON)
  3) LLM 调用 ×1：给两张概念卡，判定是否同一技巧并产出合并结果

依赖：anthropic SDK。设置环境变量 ANTHROPIC_API_KEY 后直接运行。
若未设置 key：脚本仍会完成第 1 步抽取，并把将要发给 LLM 的 prompt/输入
落盘到 poc/output/canon_inputs.json，便于离线检查或换 key 复跑。

遵循 claude-api 约定：tool use 结构化输出 + prompt caching（缓存静态 system/schema）。
"""
from __future__ import annotations
import os, re, json, sys, zipfile, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "poc" / "output"
OUTDIR.mkdir(parents=True, exist_ok=True)

SAMPLES = {
    "专题2.3": ROOT / "20260530/03_平面向量/专题2.3 平面向量中极化恒等式及常见公式应用 解析版.docx",
    "培优06": ROOT / "20260530/03_平面向量/培优06 拓展专题之二：巧用极化恒等式解决平面向量问题（期末复习讲义）（解析版）.docx",
}

MODEL = "claude-opus-4-8"  # 最新最强；判同任务对准确性敏感，值得用 opus

# ---------------------------------------------------------------------------
# 1) 确定性抽取：docx -> 与「极化恒等式」相关的正文片段
#    生产中此处应接 scripts/omml2latex.py 把公式对象转 LaTeX；本 POC 用朴素文本，
#    公式会退化为如 "a∙b= 14a+b2-a-b2"（=¼(|a+b|²-|a-b|²)），但语义主体保留。
# ---------------------------------------------------------------------------
def docx_text(path: pathlib.Path) -> str:
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    txt = re.sub(r"<[^>]+>", "", xml)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{2,}", "\n", txt)
    return txt.strip()

def relevant_excerpt(txt: str, keyword: str = "极化恒等式", max_chars: int = 3500) -> str:
    lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
    keep = [ln for ln in lines if keyword in ln or any(
        k in ln for k in ["数量积", "中线", "几何意义", "公式", "适用", "题型", "知识点", "结论"])]
    excerpt = "\n".join(keep)
    return excerpt[:max_chars]

# ---------------------------------------------------------------------------
# 2) & 3) LLM：tool-use 强制 JSON 输出
# ---------------------------------------------------------------------------
CONCEPT_CARD_TOOL = {
    "name": "emit_concept_card",
    "description": "把一段数学讲义里描述的某个『技巧』抽成结构化概念卡。判同只看数学内核，不看措辞。",
    "input_schema": {
        "type": "object",
        "properties": {
            "canonical_name": {"type": "string", "description": "规范名（去掉『巧用/速解』等修饰，取学界通用名）"},
            "name_raw": {"type": "string", "description": "原文里的叫法/标题"},
            "core_latex": {"type": "string", "description": "核心公式/定理（LaTeX，尽量复原）"},
            "applicable_conditions": {"type": "string", "description": "适用条件（什么结构/场景才能用）"},
            "conclusion_use": {"type": "string", "description": "作用/能解决什么问题"},
            "related_kp": {"type": "array", "items": {"type": "string"}, "description": "关联知识点"},
            "evidence_excerpt": {"type": "string", "description": "支撑判断的最关键原文片段（<=120字）"},
        },
        "required": ["canonical_name", "name_raw", "core_latex", "applicable_conditions", "conclusion_use"],
    },
}

MATCH_TOOL = {
    "name": "emit_match_decision",
    "description": "判定两张技巧概念卡是否指向同一个技巧；若是，产出合并后的 canonical 节点。",
    "input_schema": {
        "type": "object",
        "properties": {
            "same": {"type": "boolean", "description": "是否同一技巧"},
            "canonical_name": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}, "description": "合并的各来源叫法"},
            "unified_core_latex": {"type": "string"},
            "confidence": {"type": "number", "description": "0~1，低于 0.75 应转人工复核"},
            "reasoning": {"type": "string", "description": "判同/判异的依据，必须落到数学内核"},
        },
        "required": ["same", "confidence", "reasoning"],
    },
}

EXTRACT_SYSTEM = (
    "你是数学知识图谱的抽取器。给你一段高中数学讲义正文，请抽出其中描述的核心『技巧』，"
    "调用 emit_concept_card 输出。原则：concept card 的 core_latex / applicable_conditions "
    "刻画的是『数学内核』，与作者措辞、章节编号、组织方式无关。"
)
JUDGE_SYSTEM = (
    "你是知识图谱实体归一裁决器。给你两张来自不同来源的『技巧概念卡』，"
    "判断它们是否是同一个技巧。判同的唯一依据是数学内核（公式、适用条件、结论），"
    "而不是名字是否相同、组织方式是否相同。调用 emit_match_decision 输出。"
)

def call_tool(client, system, user_text, tool):
    """单轮 tool-use 调用，强制走指定工具，返回工具输入 dict。system+schema 做 prompt caching。"""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user_text}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("no tool_use in response")

def main():
    # ---- step 1: 确定性抽取 ----
    excerpts = {}
    for label, path in SAMPLES.items():
        if not path.exists():
            print(f"[ERR] 样本缺失: {path}", file=sys.stderr); sys.exit(2)
        excerpts[label] = relevant_excerpt(docx_text(path))
    print("== step1 抽取片段长度 ==")
    for label, ex in excerpts.items():
        print(f"  {label}: {len(ex)} 字")

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        dump = OUTDIR / "canon_inputs.json"
        dump.write_text(json.dumps({
            "model": MODEL,
            "extract_system": EXTRACT_SYSTEM,
            "judge_system": JUDGE_SYSTEM,
            "concept_card_tool": CONCEPT_CARD_TOOL,
            "match_tool": MATCH_TOOL,
            "excerpts": excerpts,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[WARN] 未设置 ANTHROPIC_API_KEY；已把 LLM 输入落盘到 {dump}")
        print("       设置 key 后重跑即可看到真实 LLM 抽取 + 判同结果。")
        return

    import anthropic
    client = anthropic.Anthropic(api_key=key)

    # ---- step 2: 各自抽概念卡 ----
    cards = {}
    for label, ex in excerpts.items():
        card = call_tool(client, EXTRACT_SYSTEM,
                         f"【来源：{label}】讲义正文片段：\n{ex}", CONCEPT_CARD_TOOL)
        cards[label] = card
        print(f"\n== step2 概念卡 [{label}] ==")
        print(json.dumps(card, ensure_ascii=False, indent=2))

    # ---- step 3: 判同 ----
    a, b = list(cards.values())
    decision = call_tool(
        client, JUDGE_SYSTEM,
        "概念卡A：\n" + json.dumps(a, ensure_ascii=False, indent=2) +
        "\n\n概念卡B：\n" + json.dumps(b, ensure_ascii=False, indent=2),
        MATCH_TOOL)
    print("\n== step3 判同结果 ==")
    print(json.dumps(decision, ensure_ascii=False, indent=2))

    (OUTDIR / "canon_result.json").write_text(
        json.dumps({"cards": cards, "decision": decision}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    verdict = "✅ 合并为同一 canonical 技巧" if decision.get("same") else "❌ 判为不同技巧"
    print(f"\n结论：{verdict}  (confidence={decision.get('confidence')})")

if __name__ == "__main__":
    main()
