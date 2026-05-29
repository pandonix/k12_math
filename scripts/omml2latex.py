"""OMML (Office Math Markup Language) -> LaTeX converter.

Converts a docx `m:oMath` ElementTree node into a LaTeX string suitable for
MathJax rendering (delimited by the caller with $...$).

Pure standard-library; no external dependencies. Covers the constructs that
actually appear in the source documents: runs, fractions, sub/superscripts,
radicals, delimiters, n-ary operators, functions, accents, bars, group chars,
matrices, and lower/upper limits.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _q(tag: str) -> str:
    return f"{{{M}}}{tag}"


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


# Unicode operators/symbols -> LaTeX commands. Plain ASCII passes through.
_SYMBOLS = {
    "−": "-", "–": "-", "—": "-",
    "×": r"\times ", "÷": r"\div ", "·": r"\cdot ", "∙": r"\cdot ",
    "≤": r"\le ", "≥": r"\ge ", "≠": r"\ne ", "≈": r"\approx ",
    "±": r"\pm ", "∓": r"\mp ", "∞": r"\infty ",
    "∈": r"\in ", "∉": r"\notin ", "∋": r"\ni ",
    "⊂": r"\subset ", "⊆": r"\subseteq ", "⊄": r"\not\subset ",
    "⊃": r"\supset ", "⊇": r"\supseteq ",
    "∪": r"\cup ", "∩": r"\cap ", "∅": r"\varnothing ", "∁": r"\complement ",
    "∀": r"\forall ", "∃": r"\exists ",
    "→": r"\to ", "⇒": r"\Rightarrow ", "⇔": r"\Leftrightarrow ",
    "←": r"\leftarrow ", "↔": r"\leftrightarrow ",
    "∥": r"\parallel ", "⊥": r"\perp ", "∠": r"\angle ", "°": r"^\circ ",
    "，": ",", "、": ",", "；": ";", "：": ":",
    "√": r"\sqrt", "∑": r"\sum ", "∏": r"\prod ", "∫": r"\int ",
    "∂": r"\partial ", "∇": r"\nabla ",
    "≡": r"\equiv ", "∝": r"\propto ", "∴": r"\therefore ", "∵": r"\because ",
    "⋅": r"\cdot ", "…": r"\dots ", "⋯": r"\cdots ", "⋮": r"\vdots ", "⋱": r"\ddots ",
    "α": r"\alpha ", "β": r"\beta ", "γ": r"\gamma ", "δ": r"\delta ",
    "ε": r"\varepsilon ", "ζ": r"\zeta ", "η": r"\eta ", "θ": r"\theta ",
    "ι": r"\iota ", "κ": r"\kappa ", "λ": r"\lambda ", "μ": r"\mu ",
    "ν": r"\nu ", "ξ": r"\xi ", "π": r"\pi ", "ρ": r"\rho ",
    "σ": r"\sigma ", "τ": r"\tau ", "υ": r"\upsilon ", "φ": r"\varphi ",
    "χ": r"\chi ", "ψ": r"\psi ", "ω": r"\omega ",
    "Γ": r"\Gamma ", "Δ": r"\Delta ", "Θ": r"\Theta ", "Λ": r"\Lambda ",
    "Ξ": r"\Xi ", "Π": r"\Pi ", "Σ": r"\Sigma ", "Φ": r"\Phi ",
    "Ψ": r"\Psi ", "Ω": r"\Omega ", "φ": r"\phi ",
}

# Characters that must be escaped to be literal in LaTeX math mode.
_ESCAPE = {
    "%": r"\%", "&": r"\&", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "$": r"\$",
}


def _map_text(text: str) -> str:
    out = []
    for ch in text:
        if ch in _SYMBOLS:
            out.append(_SYMBOLS[ch])
        elif ch in _ESCAPE:
            out.append(_ESCAPE[ch])
        else:
            out.append(ch)
    return "".join(out)


def _children(el: ET.Element, tag: str) -> list[ET.Element]:
    return el.findall(_q(tag))


def _child(el: ET.Element, tag: str) -> ET.Element | None:
    return el.find(_q(tag))


def _attr_val(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    return el.get(_q("val"))


def _wrap(latex: str) -> str:
    """Wrap a sub-expression in braces only when it isn't already a single token."""
    s = latex
    if len(s) == 1:
        return s
    # already a single \command or {...} group
    if s.startswith("{") and s.endswith("}"):
        return s
    return "{" + s + "}"


def _convert_children(el: ET.Element) -> str:
    parts = []
    for child in el:
        parts.append(_convert_node(child))
    return "".join(parts)


def _convert_node(el: ET.Element) -> str:
    tag = _local(el.tag)
    handler = _HANDLERS.get(tag)
    if handler:
        return handler(el)
    # Property / formatting containers carry no renderable math -> skip.
    if tag in _SKIP:
        return ""
    # Unknown element: recurse so we don't drop nested content.
    return _convert_children(el)


# ---- element handlers -------------------------------------------------------

def _h_run(el: ET.Element) -> str:
    parts = []
    for t in el.findall(_q("t")):
        parts.append(_map_text(t.text or ""))
    return "".join(parts)


def _h_text(el: ET.Element) -> str:
    return _map_text(el.text or "")


def _h_frac(el: ET.Element) -> str:
    num = _child(el, "num")
    den = _child(el, "den")
    fpr = _child(el, "fPr")
    ftype = _attr_val(_child(fpr, "type")) if fpr is not None else None
    n = _convert_children(num) if num is not None else ""
    d = _convert_children(den) if den is not None else ""
    if ftype == "lin":
        return f"{_wrap(n)}/{_wrap(d)}"
    if ftype == "noBar":
        return f"\\binom{{{n}}}{{{d}}}"
    return f"\\frac{{{n}}}{{{d}}}"


def _h_ssup(el: ET.Element) -> str:
    base = _child(el, "e")
    sup = _child(el, "sup")
    b = _convert_children(base) if base is not None else ""
    s = _convert_children(sup) if sup is not None else ""
    return f"{_wrap(b)}^{_wrap(s)}"


def _h_ssub(el: ET.Element) -> str:
    base = _child(el, "e")
    sub = _child(el, "sub")
    b = _convert_children(base) if base is not None else ""
    s = _convert_children(sub) if sub is not None else ""
    return f"{_wrap(b)}_{_wrap(s)}"


def _h_ssubsup(el: ET.Element) -> str:
    base = _child(el, "e")
    sub = _child(el, "sub")
    sup = _child(el, "sup")
    b = _convert_children(base) if base is not None else ""
    sb = _convert_children(sub) if sub is not None else ""
    sp = _convert_children(sup) if sup is not None else ""
    return f"{_wrap(b)}_{_wrap(sb)}^{_wrap(sp)}"


def _h_rad(el: ET.Element) -> str:
    radpr = _child(el, "radPr")
    deg = _child(el, "deg")
    e = _child(el, "e")
    body = _convert_children(e) if e is not None else ""
    hide = radpr is not None and _attr_val(_child(radpr, "degHide")) in {"1", "true", "on"}
    deg_txt = _convert_children(deg) if deg is not None else ""
    if deg_txt and not hide:
        return f"\\sqrt[{deg_txt}]{{{body}}}"
    return f"\\sqrt{{{body}}}"


_DELIM_MAP = {
    "(": "(", ")": ")", "[": "[", "]": "]",
    "{": r"\{", "}": r"\}", "|": "|", "‖": r"\|",
    "⟨": r"\langle ", "⟩": r"\rangle ", "⌊": r"\lfloor ", "⌋": r"\rfloor ",
    "⌈": r"\lceil ", "⌉": r"\rceil ",
}


def _h_delim(el: ET.Element) -> str:
    dpr = _child(el, "dPr")
    beg, end, sep = "(", ")", "|"
    if dpr is not None:
        beg = _attr_val(_child(dpr, "begChr")) or "("
        end = _attr_val(_child(dpr, "endChr"))
        end = end if end is not None else ")"
        sep = _attr_val(_child(dpr, "sepChr")) or "|"
    inner = [_convert_children(e) for e in _children(el, "e")]
    sep_l = _DELIM_MAP.get(sep, sep)
    content = (sep_l + " ").join(inner) if len(inner) > 1 else (inner[0] if inner else "")
    lb = _DELIM_MAP.get(beg, beg) if beg else "."
    rb = _DELIM_MAP.get(end, end) if end else "."
    lb = lb or "."
    rb = rb or "."
    return f"\\left{lb}{content}\\right{rb}"


def _h_nary(el: ET.Element) -> str:
    narypr = _child(el, "naryPr")
    chr_ = _attr_val(_child(narypr, "chr")) if narypr is not None else None
    op = _SYMBOLS.get(chr_, None) if chr_ else None
    if op is None:
        op = {None: r"\int ", "": r"\int "}.get(chr_, _map_text(chr_) if chr_ else r"\int ")
    sub = _child(el, "sub")
    sup = _child(el, "sup")
    e = _child(el, "e")
    out = op.rstrip()
    s_sub = _convert_children(sub) if sub is not None else ""
    s_sup = _convert_children(sup) if sup is not None else ""
    if s_sub:
        out += f"_{_wrap(s_sub)}"
    if s_sup:
        out += f"^{_wrap(s_sup)}"
    body = _convert_children(e) if e is not None else ""
    return f"{out} {body}"


_FUNC_NAMES = {
    "sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "lg", "exp",
    "lim", "max", "min", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
}


def _h_func(el: ET.Element) -> str:
    fname = _child(el, "fName")
    e = _child(el, "e")
    name = _convert_children(fname) if fname is not None else ""
    body = _convert_children(e) if e is not None else ""
    base = name.strip()
    cmd = f"\\{base}" if base in _FUNC_NAMES else r"\operatorname{" + base + "}" if base else ""
    return f"{cmd} {body}".strip()


_ACCENT_MAP = {
    "̂": "hat", "^": "hat",
    "̃": "tilde", "~": "tilde",
    "̄": "bar", "¯": "bar",
    "̇": "dot", "̈": "ddot",
    "⃗": "vec", "→": "vec",
    "̀": "grave", "́": "acute", "̌": "check",
}


def _h_acc(el: ET.Element) -> str:
    accpr = _child(el, "accPr")
    chr_ = _attr_val(_child(accpr, "chr")) if accpr is not None else None
    e = _child(el, "e")
    body = _convert_children(e) if e is not None else ""
    cmd = _ACCENT_MAP.get(chr_ or "̂", "hat")
    return f"\\{cmd}{{{body}}}"


def _h_bar(el: ET.Element) -> str:
    barpr = _child(el, "barPr")
    pos = _attr_val(_child(barpr, "pos")) if barpr is not None else None
    e = _child(el, "e")
    body = _convert_children(e) if e is not None else ""
    return f"\\underline{{{body}}}" if pos == "bot" else f"\\overline{{{body}}}"


def _h_groupchr(el: ET.Element) -> str:
    gpr = _child(el, "groupChrPr")
    chr_ = _attr_val(_child(gpr, "chr")) if gpr is not None else None
    pos = _attr_val(_child(gpr, "pos")) if gpr is not None else None
    e = _child(el, "e")
    body = _convert_children(e) if e is not None else ""
    if chr_ in ("⏟", "︸"):
        return f"\\underbrace{{{body}}}"
    if chr_ in ("⏞", "︷"):
        return f"\\overbrace{{{body}}}"
    if pos == "top":
        return f"\\overset{{{_map_text(chr_ or '')}}}{{{body}}}"
    return f"\\underset{{{_map_text(chr_ or '')}}}{{{body}}}"


def _h_limlow(el: ET.Element) -> str:
    e = _child(el, "e")
    lim = _child(el, "lim")
    body = _convert_children(e) if e is not None else ""
    sub = _convert_children(lim) if lim is not None else ""
    base = body.strip()
    if base == "lim" or base == r"\lim":
        return f"\\lim_{{{sub}}}"
    return f"\\underset{{{sub}}}{{{body}}}"


def _h_limupp(el: ET.Element) -> str:
    e = _child(el, "e")
    lim = _child(el, "lim")
    body = _convert_children(e) if e is not None else ""
    sup = _convert_children(lim) if lim is not None else ""
    return f"\\overset{{{sup}}}{{{body}}}"


def _h_matrix(el: ET.Element) -> str:
    rows = []
    for mr in _children(el, "mr"):
        cells = [_convert_children(e) for e in _children(mr, "e")]
        rows.append(" & ".join(cells))
    body = " \\\\ ".join(rows)
    return f"\\begin{{matrix}}{body}\\end{{matrix}}"


_HANDLERS = {
    "r": _h_run,
    "t": _h_text,
    "f": _h_frac,
    "sSup": _h_ssup,
    "sSub": _h_ssub,
    "sSubSup": _h_ssubsup,
    "rad": _h_rad,
    "d": _h_delim,
    "nary": _h_nary,
    "func": _h_func,
    "acc": _h_acc,
    "bar": _h_bar,
    "groupChr": _h_groupchr,
    "limLow": _h_limlow,
    "limUpp": _h_limupp,
    "m": _h_matrix,
    "e": _convert_children,
    "num": _convert_children,
    "den": _convert_children,
    "sup": _convert_children,
    "sub": _convert_children,
    "deg": _convert_children,
    "oMath": _convert_children,
    "oMathPara": _convert_children,
}

# Property containers and run-level formatting we intentionally ignore.
_SKIP = {
    "fPr", "sSupPr", "sSubPr", "sSubSupPr", "radPr", "dPr", "naryPr",
    "funcPr", "accPr", "barPr", "groupChrPr", "limLowPr", "limUppPr",
    "mPr", "mr",  # mr handled inside matrix; standalone skip
    "ctrlPr", "rPr", "rFonts", "i", "b", "color", "sz", "szCs", "nor",
    "mcs", "mc", "mcPr", "count", "mcJc", "scr", "sty", "brk", "argPr",
}


def omml_to_latex(el: ET.Element) -> str:
    """Convert an m:oMath (or m:oMathPara) element to a LaTeX string."""
    latex = _convert_node(el)
    # collapse redundant whitespace introduced by symbol commands
    return " ".join(latex.split()).replace(" }", "}").replace("{ ", "{")


if __name__ == "__main__":
    import sys
    import zipfile

    path = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    count = 0
    seen = set()
    for om in root.iter(_q("oMath")):
        latex = omml_to_latex(om)
        if not latex.strip() or latex in seen:
            continue
        seen.add(latex)
        print(f"$ {latex} $")
        count += 1
        if count >= limit:
            break
