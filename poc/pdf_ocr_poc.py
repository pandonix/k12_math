#!/usr/bin/env python3
"""PDF → 题库 POC：验证 PDF 走"视觉 OCR → LaTeX"能接上现有渲染层。

背景：现有 docx 方案吃 OOXML 结构（OMML/WMF），PDF 没有这些结构，朴素文本
抽取会把数学打成乱码（α→\\uf061、分数压平）。本 POC 演示正确路径：

  PDF 页面 --(PyMuPDF 渲染)--> PNG --(视觉 OCR / claude provider)--> 结构化 $latex$
  --> 复用现有 token 约定（$…$ + [[img|宽x高]]）--> MathJax 渲染

运行后在 poc/output/pdf_ocr_poc/ 生成：
  - 各样例页 PNG（OCR 的输入）
  - naive_extract.txt（朴素抽取的乱码，作对照）
  - preview.html（左：原 PDF 页图；右：视觉 OCR 出的 LaTeX 经 MathJax 渲染）

注意：本 POC 中"视觉 OCR"的结果由人工/模型读图产出（见 OCR_RESULTS），
生产环境即由 backend 的 OCR provider（claude 视觉）自动完成，输出同样的
结构进库。即下游渲染层完全复用，只需替换上游提取器。
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "poc" / "output" / "pdf_ocr_poc"

# 样例页：(pdf 路径, 0基页号, 标签)
SAMPLES = [
    (ROOT / "data" / "高一下学期数学26个易混易错全归纳（解析版）.pdf", 2, "易混易错·典例2"),
]

# 视觉 OCR 产出（读 PNG 得到）。生产环境由 claude provider 自动产生同结构。
# 完全沿用现有 DB 字段与 token 约定：正文用 $latex$，配图用 [[img:path|宽x高]]。
OCR_RESULTS = {
    "易混易错·典例2": {
        "stem_md": (
            "【典例2】（25-26 高三·全国·专题练习）已知角 $\\alpha$ 的终边过点 "
            "$A(-3,m)$ 且 $\\sin\\alpha=\\dfrac{4}{5}$，则 $m=$（ ）\n"
            "A．$3$　B．$4$　C．$\\pm 3$　D．$\\pm 4$"
        ),
        "answer_md": "B",
        "solution_md": (
            "角 $\\alpha$ 的终边过点 $A(-3,m)$ 且 $\\sin\\alpha=\\dfrac{4}{5}$，\n"
            "所以 $\\dfrac{m}{\\sqrt{(-3)^2+m^2}}=\\dfrac{4}{5}$ 且 $m>0$，解得 $m=4$。\n"
            "故选：B."
        ),
    },
}


def render_page(pdf_path: Path, page_index: int, out_png: Path, zoom: float = 3.0) -> tuple[int, int]:
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    pix.save(out_png)
    naive = page.get_text("text")
    doc.close()
    return naive, (pix.width, pix.height)


def build_html(items: list[dict]) -> str:
    blocks = []
    for it in items:
        ocr = it["ocr"]
        body = ""
        if ocr.get("stem_md"):
            body += f"<h4>题干</h4><div class='md'>{html.escape(ocr['stem_md'])}</div>"
        if ocr.get("answer_md"):
            body += f"<h4>答案</h4><div class='md'>{html.escape(ocr['answer_md'])}</div>"
        if ocr.get("solution_md"):
            body += f"<h4>解析</h4><div class='md'>{html.escape(ocr['solution_md'])}</div>"
        blocks.append(f"""
        <section class="sample">
          <h2>{html.escape(it['tag'])}</h2>
          <div class="cols">
            <div class="col"><div class="cap">① PDF 原页（OCR 输入）</div>
              <img src="{it['png_name']}" alt="pdf page"></div>
            <div class="col"><div class="cap">② 视觉 OCR→LaTeX 经 MathJax 渲染（现有渲染层）</div>
              <div class="rendered">{body}</div></div>
          </div>
          <details><summary>③ 对照：朴素文本抽取（乱码，证明不可用）</summary>
            <pre>{html.escape(it['naive'][:1200])}</pre></details>
        </section>""")

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>PDF→题库 OCR POC</title>
<script>window.MathJax={{tex:{{inlineMath:[["$","$"]],displayMath:[["$$","$$"]]}},svg:{{fontCache:"global"}}}};</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<style>
 body{{font-family:-apple-system,system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#1f2937;line-height:1.7}}
 h1{{font-size:20px}} .sample{{border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:20px 0}}
 .cols{{display:flex;gap:16px;flex-wrap:wrap}} .col{{flex:1;min-width:320px}}
 .cap{{font-size:12px;color:#6b7280;margin-bottom:6px}}
 .col img{{width:100%;border:1px solid #e5e7eb;border-radius:8px}}
 .rendered{{border:1px solid #e5e7eb;border-radius:8px;padding:12px;background:#fff}}
 .rendered h4{{margin:.6em 0 .2em;color:#059669}} .md{{white-space:pre-wrap}}
 pre{{white-space:pre-wrap;background:#f9fafb;padding:10px;border-radius:8px;font-size:12px;color:#b91c1c}}
 details{{margin-top:10px}}
</style></head>
<body>
<h1>PDF → 题库：视觉 OCR → LaTeX POC</h1>
<p>左为 PDF 原页，右为"视觉 OCR 产出的 LaTeX"经现有 MathJax 渲染层显示。底部可展开看朴素文本抽取的乱码对照。</p>
{''.join(blocks)}
</body></html>"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    naive_dump = []
    for pdf_path, idx, tag in SAMPLES:
        png_name = f"{tag.replace('·','_')}.png"
        naive, size = render_page(pdf_path, idx, OUT / png_name)
        naive_dump.append(f"### {tag} (page {idx+1}) {size}\n{naive}\n")
        items.append({"tag": tag, "png_name": png_name, "naive": naive, "ocr": OCR_RESULTS.get(tag, {})})
    (OUT / "naive_extract.txt").write_text("\n".join(naive_dump), encoding="utf-8")
    (OUT / "preview.html").write_text(build_html(items), encoding="utf-8")
    (OUT / "ocr_results.json").write_text(json.dumps(OCR_RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print("POC 输出:", OUT)
    for f in sorted(OUT.iterdir()):
        print("  -", f.name)


if __name__ == "__main__":
    main()
