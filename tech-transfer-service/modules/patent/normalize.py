"""把上游专利检索结果收成对外契约，并去掉源站痕迹。"""

from __future__ import annotations

import html
import math
import re

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
_SEMANTIC_TAG_RE = re.compile(r"<(sub|sup)\b[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
_MARKER_RE = re.compile(r"\ue000(0|1)\|(.*?)\ue001", re.DOTALL)
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
_TEX_SQRT_RE = re.compile(r"\\sqrt\{([^{}]*)\}")
_TEX_SCRIPT_RE = re.compile(r"([A-Za-zΑ-ωϐϑϕϖ0-9∑∏∫])([_^])(?:\{([^{}]+)\}|([^\s{}]))")
_TEX_LIMITS_RE = re.compile(r"([∑∏∫])_\{([^{}]+)\}\^\{([^{}]+)\}")
_TEX_SIMPLE_COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
_TEX_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "theta": "θ",
    "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "phi": "φ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Omega": "Ω",
    "sum": "∑", "prod": "∏", "int": "∫", "infty": "∞", "partial": "∂", "nabla": "∇",
    "times": "×", "cdot": "·", "pm": "±", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥",
    "neq": "≠", "approx": "≈", "rightarrow": "→", "leftarrow": "←", "to": "→", "degree": "°",
    "quad": " ", "qquad": "  ", "left": "", "right": "", "mathrm": "", "text": "", "operatorname": "",
}
_SOURCE_URL_RE = re.compile(
    r"https?://[^\s\"'<>]*(?:googleapis|googleusercontent|patents\.google|patentimages\.storage|google\.com/patent)[^\s\"'<>]*",
    re.IGNORECASE,
)
_PUB_NO_RE = re.compile(r"^[A-Za-z]{1,4}[\d.]{4,24}[A-Za-z]?$", re.IGNORECASE)


def is_publication_no(value: str) -> bool:
    text = (value or "").strip()
    return bool(text) and bool(_PUB_NO_RE.match(text)) and len(text) <= 32


def clean_text(value) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub("", text)
    text = _SOURCE_URL_RE.sub("", text)
    return " ".join(text.split()).strip()


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
    text = _preserve_semantic_tags(text)
    text = _HTML_TAG_RE.sub("", text)
    text = _SOURCE_URL_RE.sub("", text)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = repair_broken_superscripts("\n".join(lines).strip())
    text = repair_broken_subscripts(text)
    text = _FORMULA_BREAK_RE.sub("", text)
    text = _SUBSCRIPT_WRAP_RE.sub("", text)
    return re.sub(r"\ue001\n(?=\S)", "\ue001", text)


def clean_multiline(value) -> str:
    return _strip_markers(_clean_multiline_rich(value))


def _tex_to_text(value: str) -> str:
    text = value.strip().replace("\\\\", "；")
    for _ in range(4):
        text = _TEX_GROUP_RE.sub(lambda match: f"({match.group(2)})/({match.group(3)})", text)
        text = _TEX_SQRT_RE.sub(lambda match: f"√({match.group(1)})", text)
    text = _TEX_SIMPLE_COMMAND_RE.sub(lambda match: _TEX_SYMBOLS.get(match.group(1), match.group(1)), text)
    return text.replace("{", "").replace("}", "")


def _tex_to_html(value: str) -> str:
    """把常见 TeX 转成小程序 rich-text 可识别的安全 HTML，而非把 TeX 原样塞给页面。"""
    # 先转义上游原文，再插入本函数生成的受控标签，避免公式内容成为 HTML 注入点。
    text = html.escape(value.strip().replace("\\\\", "；"))
    for _ in range(4):
        text = _TEX_GROUP_RE.sub(
            lambda match: '<span style="display:inline-block;text-align:center;vertical-align:middle;line-height:1.1">'
            f'<span style="display:block;border-bottom:1px solid #475569">{_tex_to_html(match.group(2))}</span>'
            f'<span style="display:block">{_tex_to_html(match.group(3))}</span></span>',
            text,
        )
        text = _TEX_SQRT_RE.sub(lambda match: f"√<span style=\"text-decoration:overline\">{_tex_to_html(match.group(1))}</span>", text)
    text = _TEX_SIMPLE_COMMAND_RE.sub(lambda match: _TEX_SYMBOLS.get(match.group(1), match.group(1)), text)
    text = _TEX_LIMITS_RE.sub(lambda match: f"{match.group(1)}<sub>{match.group(2)}</sub><sup>{match.group(3)}</sup>", text)
    text = _TEX_SCRIPT_RE.sub(
        lambda match: f"{match.group(1)}<{'sup' if match.group(2) == '^' else 'sub'}>{match.group(3) or match.group(4)}</{'sup' if match.group(2) == '^' else 'sub'}>",
        text,
    )
    return text.replace("{", "").replace("}", "")


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
        if not line:
            continue
        # 未带 Markdown/LaTeX 边界的公式可能嵌在中文语句中；不猜测边界，避免只把尾半截单独渲染。
        block_type = "formula" if _is_formula_expression(line) else "paragraph"
        blocks.append(_rich_block(block_type, _strip_markers(line), _inline_html(line)))
    return blocks


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def _is_math_fragment(text: str) -> bool:
    if not text or _contains_cjk(text) or len(text) > 100:
        return False
    return bool(re.search(r"[=＝+\-×÷*/^_∑∏∫σδελφρμ]|^[A-Za-zΑ-ωϐϑϕϖ][A-Za-z0-9′′']*$|^\([0-9.\-]+\)$", text))


def _is_formula_expression(text: str) -> bool:
    return not _contains_cjk(text) and bool(re.search(r"[=＝+\-×÷*/∑∏∫]", text))


def _coalesce_math_lines(text: str) -> list[str]:
    """只合并连续的数学短行，保留普通中文段落的换行边界。"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
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
        if len(run) > 1 and any(re.search(r"[=＝+\-×÷*/∑∏∫σδελφρμ]", part) for part in run):
            merged.append("".join(run))
        else:
            merged.extend(run)
        index = next_index
    return merged


def _rich_block(block_type: str, text: str, rendered_html: str, **extra) -> dict[str, str]:
    block = {"type": block_type, "text": text, **extra}
    # 为旧客户端维持仅含 type/text 的简单块结构；有真实富文本语义时才附加 html。
    if rendered_html != html.escape(text):
        block["html"] = rendered_html
    return block


def format_patent_content_blocks(value) -> list[dict[str, str]]:
    """识别专利正文的段落、TeX/Markdown 公式、代码及上游断裂的上下标。"""
    text = _clean_multiline_rich(value)
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
