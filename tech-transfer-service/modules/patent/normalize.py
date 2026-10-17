"""把上游专利检索结果收成对外契约，并去掉源站痕迹。"""

from __future__ import annotations

import html
import math
import re
import xml.etree.ElementTree as ET

from opencc import OpenCC

# 对外禁止出现的源站域名/路径片段（大小写不敏感）
_LEAK_MARKERS = (
    "googleapis.com",
    "googleusercontent.com",
    "patents.google",
    "patentimages.storage",
    "google.com/patents",
    "google.com/patent",
)

_DROP_KEYS = {
    "pdf_url",
    "thumbnail",
    "patent_id",
    "patentId",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MATHML_CONTAINER_RE = re.compile(
    r"<(maths|math)\b[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL
)
_SEMANTIC_TAG_RE = re.compile(r"<(sub|sup)\b[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
_MARKER_RE = re.compile(r"\ue000(0|1)\|(.*?)\ue001", re.DOTALL)
# 上游把谷歌专利页的 <math> 按 mi/mo/mn 逐节点展平，分式/根号结构随之丢失，
# 只留下 MathML 里的不可见运算符与方向控制符。这些字符不占宽度，
# 只含它们的行会在页面上渲染成空白段落（正文公式区“一点没显示”的直接原因）。
_INVISIBLE_TIMES_RE = re.compile("[\u2062\u2063]")
_INVISIBLE_MATH_RE = re.compile("[\u2061\u2064\u200b-\u200f\u2028\u2029\ufeff\u00ad]")
# 上游把角标拆成独立行：h\n1 → h₁，ρ\ns → ρₛ，k\n∞ → k<sub>∞</sub>。
# 变量限定为拉丁/希腊单字母，避免把 Figure\n1 等普通文字误判成角标。
_BROKEN_SUB_RE = re.compile(
    r"(?<![A-Za-z])([A-Za-zΑ-ωϐϑϕϖ])\n([0-9A-Za-zΑ-ωϐϑϕϖ∞,]{1,16})(?=\n|$|[^A-Za-z0-9])"
)
_SUB_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUB_LETTERS = str.maketrans("aehijklmnoprstuvx", "ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
_SUPER_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_BROKEN_EXPONENT_RE = re.compile(r"([0-9]+)\n([0-9]{1,3})(?=\n(?:[A-Za-zμ]))")
_BROKEN_UNIT_POWER_RE = re.compile(r"([cm])\n([23])(?=\n|$|[，。；;])", re.IGNORECASE)
_FORMULA_BREAK_RE = re.compile(r"(?<=[A-Za-z0-9₀-₉ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ⁰¹²³⁴⁵⁶⁷⁸⁹])\n(?=[,，;；)=+\-*/])")
_SUBSCRIPT_WRAP_RE = re.compile(r"(?<=[₀-₉ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ⁰¹²³⁴⁵⁶⁷⁸⁹])\n(?=\S)")
_FORMULA_RE = re.compile(r"(?<=[：:])([A-Za-z][A-Za-z0-9]*\([^。\n]*[=＝][^。\n]*)")
_FENCED_BLOCK_RE = re.compile(r"(?m)^(?:```|~~~)([A-Za-z0-9_+-]*)[ \t]*\n?(.*?)(?:```|~~~)", re.DOTALL)
_DISPLAY_MATH_RE = re.compile(
    r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\begin\{(?:equation|align|gather)\*?\}(.+?)\\end\{(?:equation|align|gather)\*?\}",
    re.DOTALL,
)
_INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$|\\\((.+?)\\\)")
_TEX_GROUP_RE = re.compile(r"\\(frac|dfrac|tfrac)\{((?:[^{}]|\{[^{}]*\})*)\}\{((?:[^{}]|\{[^{}]*\})*)\}")
_TEX_SQRT_RE = re.compile(r"\\sqrt(?:\[([^\]]+)\])?\{([^{}]*)\}")
_TEX_SUBSUP_RE = re.compile(r"([A-Za-zΑ-ωϐϑϕϖ0-9∑∏∫])_\{([^{}]+)\}\^\{([^{}]+)\}")
_TEX_SUPSUB_RE = re.compile(r"([A-Za-zΑ-ωϐϑϕϖ0-9∑∏∫])\^\{([^{}]+)\}_\{([^{}]+)\}")
_FLATTENED_SINR_RE = re.compile(
    r"SINR\s*=\s*Signal[\s\u2062]*level\s*Interference\s*\+[\s\u2062]*Noise[\s\u2062]*level",
    re.IGNORECASE,
)
_FLATTENED_SINR_ZH_RE = re.compile(r"SINR\s*=\s*信号电平\s*干扰\s*\+\s*噪声电平", re.I)
_TEX_SCRIPT_RE = re.compile(r"([A-Za-zΑ-ωϐϑϕϖ0-9∑∏∫])([_^])(?:\{([^{}]+)\}|([^\s{}]))")
# x_i^2 这类连续脚本必须一次吃掉，否则先替换下标后上标就失去可匹配的底数。
_TEX_SCRIPT_CHAIN_RE = re.compile(
    r"([A-Za-zΑ-ωϐϑϕϖ0-9∑∏∫])((?:(?:_\{[^{}]*\}|\^\{[^{}]*\}|[_^][^\s{}]))+)"
)
_TEX_SCRIPT_PART_RE = re.compile(r"([_^])(?:\{([^{}]*)\}|([^\s{}]))")
_TEX_LIMITS_RE = re.compile(r"([∑∏∫])_\{([^{}]+)\}\^\{([^{}]+)\}")
_TEX_ENV_RE = re.compile(r"\\(?:begin|end)\{[^{}]*\}")
_TEX_SPACING_RE = re.compile(r"\\[,;:!> ]")
_TEX_SIMPLE_COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
_TEX_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "theta": "θ", "vartheta": "ϑ", "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ",
    "phi": "φ", "varphi": "φ", "omega": "ω", "xi": "ξ", "eta": "η", "zeta": "ζ", "kappa": "κ",
    "nu": "ν", "tau": "τ", "chi": "χ", "psi": "ψ",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ",
    "Phi": "Φ", "Omega": "Ω", "Psi": "Ψ", "Xi": "Ξ",
    "sum": "∑", "prod": "∏", "int": "∫", "iint": "∬", "oint": "∮", "infty": "∞",
    "partial": "∂", "nabla": "∇", "prime": "′", "circ": "∘",
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓", "ast": "∗",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "sim": "∼", "simeq": "≃", "propto": "∝",
    "ll": "≪", "gg": "≫", "lll": "⋘", "ggg": "⋙",
    "rightarrow": "→", "leftarrow": "←", "to": "→", "gets": "←",
    "leftrightarrow": "↔", "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "supset": "⊃",
    "subseteq": "⊆", "supseteq": "⊇", "cup": "∪", "cap": "∩", "emptyset": "∅",
    "forall": "∀", "exists": "∃", "neg": "¬", "wedge": "∧", "vee": "∨",
    "angle": "∠", "perp": "⊥", "parallel": "∥", "degree": "°", "ell": "ℓ",
    "cdots": "⋯", "ldots": "…", "dots": "…", "vdots": "⋮", "ddots": "⋱",
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "quad": " ", "qquad": "  ", "left": "", "right": "", "mathrm": "", "mathit": "",
    "mathbf": "", "mathsf": "", "mathtt": "", "mathcal": "", "mathbb": "", "boldsymbol": "",
    "text": "", "textrm": "", "textbf": "", "operatorname": "", "limits": "", "nolimits": "",
    "overline": "", "underline": "", "hat": "", "bar": "", "vec": "", "dot": "", "ddot": "",
    "displaystyle": "", "textstyle": "", "scriptstyle": "",
}
_SOURCE_URL_RE = re.compile(
    r"https?://[^\s\"'<>]*(?:googleapis|googleusercontent|patents\.google|patentimages\.storage|google\.com/patent)[^\s\"'<>]*",
    re.IGNORECASE,
)
_PUB_NO_RE = re.compile(r"^[A-Za-z]{1,4}[\d.]{4,24}[A-Za-z]?$", re.IGNORECASE)
# t2s 只做字形；tw2sp 同时把台湾用词收到大陆简体（軟體→软件、資訊→信息）。
# 词典进程内加载一次。无 CJK 的英/数字字段直接跳过。
_T2S = OpenCC("tw2sp")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def is_publication_no(value: str) -> bool:
    text = (value or "").strip()
    return bool(text) and bool(_PUB_NO_RE.match(text)) and len(text) <= 32


def to_simplified(text: str) -> str:
    """把繁体中文转为简体。英文、公开号、无汉字文本原样返回。"""
    if not text or not _CJK_RE.search(text):
        return text
    return _T2S.convert(text)


def clean_text(value) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub("", text)
    text = _SOURCE_URL_RE.sub("", text)
    return to_simplified(" ".join(text.split()).strip())


def _semantic_marker(kind: str, value: str) -> str:
    return f"\ue000{'0' if kind.lower() == 'sub' else '1'}|{_HTML_TAG_RE.sub('', value)}\ue001"


def _preserve_semantic_tags(text: str) -> str:
    return _SEMANTIC_TAG_RE.sub(lambda match: _semantic_marker(match.group(1), match.group(2)), text)


def _strip_markers(text: str) -> str:
    return _MARKER_RE.sub(lambda match: match.group(2), text)


def repair_broken_subscripts(text: str) -> str:
    """把 OCR/HTML 转纯文本时拆行的变量角标拼回去。"""
    if not text or "\n" not in text:
        return text
    def replace(match: re.Match) -> str:
        index = match.group(2)
        rendered = "".join(char.translate(_SUB_DIGITS) if char.isdigit() else char.lower().translate(_SUB_LETTERS) for char in index)
        if any(char not in "₀₁₂₃₄₅₆₇₈₉ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ" for char in rendered):
            return match.group(1) + _semantic_marker("sub", index)
        return match.group(1) + rendered

    return _BROKEN_SUB_RE.sub(replace, text)


def repair_broken_superscripts(text: str) -> str:
    """把科学计数法及立方/平方单位在上游抽取时断开的指数恢复出来。"""
    text = _BROKEN_EXPONENT_RE.sub(lambda match: match.group(1) + match.group(2).translate(_SUPER_DIGITS), text)
    return _BROKEN_UNIT_POWER_RE.sub(lambda match: match.group(1) + match.group(2).translate(_SUPER_DIGITS), text)


def _clean_multiline_rich(value) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _INVISIBLE_TIMES_RE.sub(" ", text)
    text = _INVISIBLE_MATH_RE.sub("", text)
    text = _preserve_semantic_tags(text)
    text = _HTML_TAG_RE.sub("", text)
    text = _SOURCE_URL_RE.sub("", text)
    lines = [
        line.rstrip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    ]
    text = repair_broken_superscripts("\n".join(lines).strip())
    text = repair_broken_subscripts(text)
    text = _FORMULA_BREAK_RE.sub("", text)
    text = _SUBSCRIPT_WRAP_RE.sub("", text)
    text = re.sub(r"\ue001\n(?=\S)", "\ue001", text)
    return to_simplified(text)


def clean_multiline(value) -> str:
    return _strip_markers(_clean_multiline_rich(value))


def _preprocess_tex(value: str) -> str:
    """统一处理 TeX 换行、环境、间距与对齐符，避免它们残留在页面上。"""
    text = value.strip().replace("\\\\", "；")
    text = _TEX_ENV_RE.sub("", text)
    text = _TEX_SPACING_RE.sub(" ", text)
    return text.replace("&", "")

def _tex_to_text(value: str) -> str:
    text = _preprocess_tex(value)
    for _ in range(4):
        text = _TEX_GROUP_RE.sub(lambda match: f"({match.group(2)})/({match.group(3)})", text)
        text = _TEX_SQRT_RE.sub(
            lambda match: f"{match.group(1) or ''}√({match.group(2)})", text
        )
    text = _TEX_SIMPLE_COMMAND_RE.sub(lambda match: _TEX_SYMBOLS.get(match.group(1), match.group(1)), text)
    return text.replace("{", "").replace("}", "")

def _render_script_chain(match: re.Match) -> str:
    """把 x_i^2 这类连续脚本逐个转成 sub/sup，而不是只转第一段。"""
    parts: list[str] = []
    for part in _TEX_SCRIPT_PART_RE.finditer(match.group(2)):
        tag = "sup" if part.group(1) == "^" else "sub"
        body = part.group(2) if part.group(2) is not None else part.group(3)
        parts.append(f"<{tag}>{_tex_to_html(body, escaped=True)}</{tag}>")
    return match.group(1) + "".join(parts)

def _tex_to_html(value: str, *, escaped: bool = False) -> str:
    """把常见 TeX 转成小程序 rich-text 可识别的安全 HTML，而非把 TeX 原样塞给页面。"""
    # 先转义上游原文，再插入本函数生成的受控标签，避免公式内容成为 HTML 注入点。
    # 递归渲染分式/根号内部时必须传 escaped=True，否则 &amp; 会被二次转义成 &amp;amp;。
    text = value.strip() if escaped else html.escape(_preprocess_tex(value))
    for _ in range(4):
        text = _TEX_GROUP_RE.sub(
            lambda match: '<span style="display:inline-block;text-align:center;vertical-align:middle;line-height:1.1">'
            f'<span style="display:block;border-bottom:1px solid #475569">{_tex_to_html(match.group(2), escaped=True)}</span>'
            f'<span style="display:block">{_tex_to_html(match.group(3), escaped=True)}</span></span>',
            text,
        )
        text = _TEX_SQRT_RE.sub(
            lambda match: (
                f"{('<sup>' + _tex_to_html(match.group(1), escaped=True) + '</sup>') if match.group(1) else ''}"
                f"√<span style=\"text-decoration:overline\">{_tex_to_html(match.group(2), escaped=True)}</span>"
            ),
            text,
        )
    text = _TEX_SIMPLE_COMMAND_RE.sub(lambda match: _TEX_SYMBOLS.get(match.group(1), match.group(1)), text)
    text = _TEX_SUBSUP_RE.sub(
        lambda match: f"{match.group(1)}<sub>{_tex_to_html(match.group(2), escaped=True)}</sub><sup>{_tex_to_html(match.group(3), escaped=True)}</sup>",
        text,
    )
    text = _TEX_SUPSUB_RE.sub(
        lambda match: f"{match.group(1)}<sup>{_tex_to_html(match.group(2), escaped=True)}</sup><sub>{_tex_to_html(match.group(3), escaped=True)}</sub>",
        text,
    )
    text = _TEX_LIMITS_RE.sub(lambda match: f"{match.group(1)}<sub>{match.group(2)}</sub><sup>{match.group(3)}</sup>", text)
    text = _TEX_SCRIPT_CHAIN_RE.sub(_render_script_chain, text)
    return text.replace("{", "").replace("}", "")

def _mathml_node_to_tex(node: ET.Element) -> str:
    """Convert common MathML presentation nodes to the TeX supported by our renderer."""
    tag = node.tag.rsplit("}", 1)[-1].lower()
    children = list(node)
    if tag in {"mi", "mn", "mtext"}:
        return "".join(node.itertext()).strip()
    if tag == "mo":
        operator = "".join(node.itertext()).strip()
        return {"⁢": " ", "⁡": "", "−": "-", "⁢⁢": " "}.get(operator, operator)
    parts = [_mathml_node_to_tex(child) for child in children]
    if tag == "mfrac" and len(parts) >= 2:
        return f"\\frac{{{parts[0]}}}{{{parts[1]}}}"
    if tag == "msqrt" and parts:
        return f"\\sqrt{{{''.join(parts)}}}"
    if tag == "mroot" and len(parts) >= 2:
        return f"\\sqrt[{parts[1]}]{{{parts[0]}}}"
    if tag == "msub" and len(parts) >= 2:
        return f"{parts[0]}_{{{parts[1]}}}"
    if tag == "msup" and len(parts) >= 2:
        return f"{parts[0]}^{{{parts[1]}}}"
    if tag == "msubsup" and len(parts) >= 3:
        return f"{parts[0]}_{{{parts[1]}}}^{{{parts[2]}}}"
    if tag in {"math", "maths", "mrow", "mstyle", "semantics", "mpadded", "mphantom"}:
        return "".join(parts)
    if tag == "mspace":
        return " "
    return "".join(parts) if parts else "".join(node.itertext()).strip()


def _mathml_to_tex(fragment: str) -> str:
    """Parse a MathML fragment; return an empty string when upstream markup is malformed."""
    math_match = re.search(r"<math\b[^>]*>(.*?)</math\s*>", fragment, re.I | re.S)
    inner = math_match.group(1) if math_match else fragment
    # MathML from patent HTML is XML-like but may contain HTML named entities.
    inner = html.unescape(inner).replace("&nbsp;", " ")
    try:
        root = ET.fromstring(f"<math>{inner}</math>")
    except ET.ParseError:
        return ""
    return _mathml_node_to_tex(root).strip()


def _replace_mathml(value) -> str:
    """Preserve MathML formula structure before general HTML tags are removed."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _INVISIBLE_TIMES_RE.sub(" ", text)
    text = _INVISIBLE_MATH_RE.sub("", text)

    def replace(match: re.Match) -> str:
        source = match.group(0)
        tex = _mathml_to_tex(source)
        if not tex:
            # A malformed formula should remain readable as text, not disappear.
            return _HTML_TAG_RE.sub("", html.unescape(source))
        return f"\n$${tex}$$\n"

    text = _MATHML_CONTAINER_RE.sub(replace, text)
    # Google Patents' plain-text export linearizes this common fraction and
    # leaves invisible multiplication operators (U+2062) between words.
    text = _FLATTENED_SINR_RE.sub(
        r"$$SINR=\\frac{Signal level}{Interference+Noise level}$$", text
    )
    return _FLATTENED_SINR_ZH_RE.sub(
        "$$SINR=\\frac{信号电平}{干扰+噪声电平}$$", text
    )


def _inline_html(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _INLINE_MATH_RE.finditer(text):
        parts.append(_markers_to_html(text[cursor:match.start()]))
        parts.append(_tex_to_html(match.group(1) or match.group(2) or ""))
        cursor = match.end()
    parts.append(_markers_to_html(text[cursor:]))
    return "".join(parts)


def _markers_to_html(text: str) -> str:
    escaped = html.escape(text)
    return _MARKER_RE.sub(
        lambda match: f"<{'sub' if match.group(1) == '0' else 'sup'}>{html.escape(match.group(2))}</{'sub' if match.group(1) == '0' else 'sup'}>",
        escaped,
    )


def _paragraph_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for line in _coalesce_math_lines(text):
        line = line.strip()
        if not line:
            continue
        # 未带 Markdown/LaTeX 边界的公式可能嵌在中文语句中；不猜测边界，避免只把尾半截单独渲染。
        block_type = "formula" if _is_formula_expression(line) else "paragraph"
        blocks.append(_rich_block(block_type, _strip_markers(line), _inline_html(line)))
    return blocks

def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))

_PROSE_WORDS = frozenset({
    "the", "of", "in", "and", "to", "for", "with", "by", "on", "at", "from",
    "a", "an", "or", "as", "that", "which", "is", "are", "was", "were", "be",
    "this", "these", "those", "it", "its", "their", "can", "may", "not", "but",
})
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_FORMULA_SIGNS_RE = re.compile(r"[=＝≈≠≤≥<>∑∏∫√∈⊂⊆∪∩∂∇]")
_FORMULA_ARITHMETIC_RE = re.compile(r"[+＋\-−×÷*/]")
_MATH_OPERATORS_RE = re.compile(r"[=＝+\-×÷*/∑∏∫σδελφρμ]")

def _looks_like_prose(text: str) -> bool:
    """英文正文常含连字符或斜杠，不能仅凭运算符就判成公式。"""
    words = _ENGLISH_WORD_RE.findall(text)
    if not words:
        return False
    if len(words) >= 8:
        return True
    return sum(1 for word in words if word.lower() in _PROSE_WORDS) >= 3

def _is_math_fragment(text: str) -> bool:
    if not text or _contains_cjk(text) or len(text) > 100:
        return False
    return bool(re.search(r"[=＝+\-×÷*/^_∑∏∫σδελφρμ]|^[A-Za-zΑ-ωϐϑϕϖ][A-Za-z0-9′′']*$|^\([0-9.\-]+\)$", text))

def _is_formula_expression(text: str) -> bool:
    stripped = text.strip()
    if not stripped or _contains_cjk(stripped) or len(stripped) > 200:
        return False
    if _FORMULA_SIGNS_RE.search(stripped):
        return True
    if not _FORMULA_ARITHMETIC_RE.search(stripped):
        return False
    return len(stripped) <= 60 and not _looks_like_prose(stripped)

def _join_math_run(parts: list[str]) -> str:
    """合并被上游拆行的公式；相邻字母片段之间补空格，运算符保持紧凑。"""
    merged = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not merged:
            merged = part
            continue
        prev, nxt = merged[-1], part[0]
        if nxt in "=＝≈≠≤≥<>∈" or prev in "=＝≈≠≤≥<>∈":
            merged += " " + part
        elif prev.isalnum() and nxt.isalnum():
            merged += " " + part
        else:
            merged += part
    return merged

def _coalesce_math_lines(text: str) -> list[str]:
    """只合并连续的数学短行，保留普通中文段落的换行边界。"""
    lines = _join_inline_fragments(_coalesce_wrapped_parenthetical_lines(text))
    merged: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_math_fragment(line):
            merged.append(line)
            index += 1
            continue
        run = [line]
        next_index = index + 1
        while next_index < len(lines) and _is_math_fragment(lines[next_index]):
            run.append(lines[next_index])
            next_index += 1
        if len(run) > 1 and any(_MATH_OPERATORS_RE.search(part) for part in run):
            merged.append(_join_math_run(run))
        else:
            merged.extend(run)
        index = next_index
    return merged

_INLINE_TAIL_WORDS = frozenset({
    "the", "of", "in", "and", "to", "for", "with", "by", "on", "at", "from",
    "a", "an", "or", "as", "that", "which", "is", "are", "its", "their",
})
_FRAGMENT_HEAD_RE = re.compile(r"^[,.;:)\]%]")
_FRAGMENT_NUMBER_RE = re.compile(r"^\d{1,4}$")
_FRAGMENT_NUMBER_HEAD_RE = re.compile(r"^\d{1,4}(?=[,.;:])")
_LOWERCASE_PHRASE_RE = re.compile(r"^[a-z][a-z\s\-]*[a-z]$")
_OPEN_TAIL_CHARS = "(（[［{"

def _should_join_fragment(prev: str, line: str) -> bool:
    if not prev or not line:
        return False
    if _FRAGMENT_HEAD_RE.match(line):
        return True
    if prev[-1] in _OPEN_TAIL_CHARS:
        return True
    if _FRAGMENT_NUMBER_RE.match(line) and (prev[-1].isalnum() or prev[-1] in "）)]】”\"'"):
        return True
    if _FRAGMENT_NUMBER_HEAD_RE.match(line) and (prev[-1].isalpha() or prev[-1] in "）)]】”\"'"):
        return True
    if prev[-1] in ".。！？!?；;：:":
        return False
    tail = prev.rsplit(" ", 1)[-1].strip().lower()
    if tail in _INLINE_TAIL_WORDS and not _CJK_RE.search(line):
        return True
    # 上游把 <figure-callout>/<b> 标注拆成独立行时，下一行通常是全小写英文短语。
    return (
        not _CJK_RE.search(prev)
        and not _CJK_RE.search(line)
        and len(line) <= 40
        and bool(_LOWERCASE_PHRASE_RE.match(line))
        and (prev[-1].isalnum() or prev[-1] in "）)]】”\"'")
    )

def _join_fragment_text(prev: str, line: str) -> str:
    if _FRAGMENT_HEAD_RE.match(line) or prev[-1] in _OPEN_TAIL_CHARS:
        return prev + line
    if _FRAGMENT_NUMBER_RE.match(line):
        return prev + line if _CJK_RE.search(prev[-1:]) else prev + " " + line
    if _FRAGMENT_NUMBER_HEAD_RE.match(line):
        return prev + line if _CJK_RE.search(prev[-1:]) else prev + " " + line
    return prev + " " + line

def _join_inline_fragments(lines: list[str]) -> list[str]:
    """把上游拆到独立行的行内标注与角标拼回整段，避免正文被切成一词一段。"""
    merged: list[str] = []
    for line in lines:
        if merged and _should_join_fragment(merged[-1], line):
            merged[-1] = _join_fragment_text(merged[-1], line)
        else:
            merged.append(line)
    return merged

def _coalesce_wrapped_parenthetical_lines(text: str) -> list[str]:
    """合并上游在未闭合括号内插入的软换行，避免学名被渲染成独立段落。"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    merged: list[str] = []
    pending = ""
    depth = 0
    opening = "(（[［【{"
    closing = ")）]］】}"

    for line in lines:
        pending += line
        for char in line:
            if char in opening:
                depth += 1
            elif char in closing and depth > 0:
                depth -= 1
        if depth == 0:
            merged.append(pending)
            pending = ""

    if pending:
        merged.append(pending)
    return merged

def _rich_block(block_type: str, text: str, rendered_html: str, **extra) -> dict[str, str]:
    block = {"type": block_type, "text": text, **extra}
    # 为旧客户端维持仅含 type/text 的简单块结构；有真实富文本语义时才附加 html。
    if rendered_html != html.escape(text):
        block["html"] = rendered_html
    return block


def format_patent_content_blocks(value) -> list[dict[str, str]]:
    """识别专利正文的段落、TeX/Markdown 公式、代码及上游断裂的上下标。"""
    text = _clean_multiline_rich(_replace_mathml(value))
    blocks: list[dict[str, str]] = []
    cursor = 0
    for fence in _FENCED_BLOCK_RE.finditer(text):
        blocks.extend(_display_math_blocks(text[cursor:fence.start()]))
        code = fence.group(2).strip("\n")
        if code:
            blocks.append({"type": "code", "text": _strip_markers(code), "language": fence.group(1).lower()})
        cursor = fence.end()
    blocks.extend(_display_math_blocks(text[cursor:]))
    return blocks


def _display_math_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    cursor = 0
    for match in _DISPLAY_MATH_RE.finditer(text):
        blocks.extend(_paragraph_blocks(text[cursor:match.start()]))
        formula = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        if formula:
            blocks.append(_rich_block("formula", _tex_to_text(formula), _tex_to_html(formula)))
        cursor = match.end()
    blocks.extend(_paragraph_blocks(text[cursor:]))
    return blocks


def clean_date(value) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    return text[:10]


def infer_patent_type(publication_no: str) -> str:
    pub = (publication_no or "").strip().upper()
    if pub.endswith("U") or pub.endswith("Y"):
        return "utility_model"
    if pub.endswith("S") or pub.endswith("D"):
        return "design"
    return "invention"


def contains_source_leak(value) -> bool:
    blob = str(value or "").lower()
    return any(marker in blob for marker in _LEAK_MARKERS)


def assert_no_source_leak(payload) -> None:
    """测试与出站前扫描：任何谷歌源站痕迹都视为实现错误。"""
    stack = [payload]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, val in cur.items():
                if str(key) in _DROP_KEYS or contains_source_leak(key):
                    raise ValueError(f"outbound leak key: {key}")
                stack.append(val)
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)
        elif contains_source_leak(cur):
            raise ValueError("outbound leak in value")


def map_search_hit(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    publication_no = clean_text(raw.get("pub_number") or raw.get("number") or "")
    if not publication_no:
        return None
    title = clean_text(raw.get("title"))
    snippet = clean_text(raw.get("snippet"))
    item = {
        "publicationNo": publication_no,
        "title": title,
        "snippet": snippet,
        "applicant": clean_text(raw.get("assignee")),
        "inventor": clean_text(raw.get("inventor")),
        "priorityDate": clean_date(raw.get("priority_date")),
        "applyDate": clean_date(raw.get("filing_date")),
        "publicationDate": clean_date(raw.get("publication_date")),
        "grantDate": clean_date(raw.get("grant_date")),
        "patentType": infer_patent_type(publication_no),
        "language": clean_text(raw.get("language"))[:8],
        "hasPdf": bool(str(raw.get("pdf_url") or "").strip()),
    }
    assert_no_source_leak(item)
    return item


def map_patent_info(raw: dict, publication_no: str, bibliographic: dict | None = None) -> dict:
    info = raw if isinstance(raw, dict) else {}
    number = clean_text(info.get("number") or publication_no)
    mapped = dict(bibliographic or {})
    mapped.update({
        "publicationNo": number or publication_no,
        "title": clean_text(info.get("title")) or mapped.get("title") or "",
        "abstract": clean_multiline(info.get("abstract")),
        "description": clean_multiline(info.get("description")),
        "claims": clean_multiline(info.get("claims")),
        "abstractBlocks": format_patent_content_blocks(info.get("abstract")),
        "descriptionBlocks": format_patent_content_blocks(info.get("description")),
        "claimsBlocks": format_patent_content_blocks(info.get("claims")),
        "patentType": mapped.get("patentType") or infer_patent_type(number or publication_no),
    })
    mapped.setdefault("snippet", "")
    mapped.setdefault("applicant", "")
    mapped.setdefault("inventor", "")
    mapped.setdefault("priorityDate", None)
    mapped.setdefault("applyDate", None)
    mapped.setdefault("publicationDate", None)
    mapped.setdefault("grantDate", None)
    mapped.setdefault("language", "")
    mapped.setdefault("hasPdf", True)
    assert_no_source_leak(mapped)
    return mapped


def page_meta(total: int, page: int, page_size: int) -> dict:
    total = max(0, int(total or 0))
    page = max(1, int(page or 1))
    page_size = max(1, min(50, int(page_size or 10)))
    total_pages = math.ceil(total / page_size) if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
    }
