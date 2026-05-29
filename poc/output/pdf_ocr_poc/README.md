# PDF → 题库 OCR POC 结论

验证：PDF 题库能否复用现有渲染方案。运行 `python3 poc/pdf_ocr_poc.py` 重现。

## 三份 PDF 的性质

| PDF | 页数 | 性质 | 朴素文本抽取 |
|---|---|---|---|
| 26个易混易错（解析版） | 66 | 电子版（有文本层） | 数学**乱码**：`α→`、`P′→P`、分数/根号压平 |
| 考前最后一课（答案版） | 101 | 电子版（学科网，含水印） | 同上 |
| 高频考点速查 | 18 | 电子版 | 简单符号 OK（`N₊ ∅ ∩ ∪`），结构化的（补集、分数）仍乱 |

结论：三份都是电子版有文本层，但 **PyMuPDF/pdfminer 朴素抽取对数学全面崩坏**——
PUA 私有区字形码 + 分数/根号结构丢失。这是 docx 一开始问题的放大版，且 **没有
OMML 这类干净结构可回收**。见 `naive_extract.txt`。

## 可行路径：视觉 OCR → LaTeX

```
PDF 页 --PyMuPDF 渲染--> PNG --视觉 OCR(claude provider)--> 结构化 $latex$
   --> 现有 token 约定（$…$ + [[img|宽x高]]）--> MathJax 渲染（零改动）
```

`preview.html`（用浏览器打开，或经本地静态服务器 `/poc/output/pdf_ocr_poc/preview.html`）
左为 PDF 原页、右为视觉 OCR 出的 LaTeX 经现有 MathJax 渲染层显示，二者一致：
`\sin\alpha=\dfrac{4}{5}`、`\dfrac{m}{\sqrt{(-3)^2+m^2}}` 等均正确。

本 POC 的"视觉 OCR"结果（`ocr_results.json`）由读图产出；生产环境即由 backend
`OCR_PROVIDER=claude` 的视觉识别自动完成，输出同一结构进库。

## 复用 / 新建 边界

- **可复用（下游，格式无关）**：DB 字段、`$latex$`/`[[img|宽x高]]` token、MathJax、前端、尺寸机制。
- **需新建（上游）**：PDF 提取器——走 `intake` 路径（已有 PyMuPDF 渲染 + OCR provider 骨架），换数学感知识别器输出 LaTeX。`omml2latex.py` / WMF 那套对 PDF 不适用。

## 待解工程问题（若推进）

- 题目切分：PDF 无干净 `【典例】` 文本流，需基于 OCR 文本或版面做切分。
- 配图/直方图：检测并裁页面区域为图，复用 B1 的"裁切透明 PNG + 尺寸 token"。
- OCR 成本与错率：需人工校对环节；可优先对"含数学"的块走 OCR、纯中文正文走文本层。
