"""从导入文本或成果简介中拆出标题、联系方式、链接等结构化字段。"""
from __future__ import annotations

import re

from modules.achievement.maturity import MATURITY_LABELS, MATURITY_LEVELS

LABEL_RE = re.compile(r"^\s*([^:：]{1,32})\s*[:：]\s*(.*)$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
URL_RE = re.compile(r"https?://[^\s）\]>，,;；]+", re.I)
SPLIT_NAMES_RE = re.compile(r"[，,、;；/]+")

FIELD_ALIASES = {
    "成果名称": "title", "中文名称": "title", "项目名称": "title", "标题": "title",
    "英文名称": "titleEn", "英文名": "titleEn",
    "成果简介": "techIntro", "技术简介": "techIntro", "项目简介": "techIntro", "简介": "techIntro",
    "来源单位": "sourceOrgName", "完成单位": "sourceOrgName", "依托单位": "sourceOrgName",
    "所属机构": "sourceOrgName", "发布单位": "sourceOrgName",
    "技术路线": "techRoute", "技术路径": "techRoute",
    "联系人": "contactName", "联系人姓名": "contactName", "对接人": "contactName",
    "团队负责人": "contactName", "负责人": "contactName",
    "联系电话": "contactPhone", "电话": "contactPhone", "手机": "contactPhone",
    "手机号": "contactPhone",
    "联系邮箱": "contactEmail", "邮箱": "contactEmail", "电子邮箱": "contactEmail",
    "Email": "contactEmail",
    "微信": "contactWechat", "微信号": "contactWechat",
    "职务": "contactTitle", "联系人职务": "contactTitle",
    "成熟度": "maturityLevel", "技术成熟度": "maturityLevel",
    "定价方式": "pricingMode",
    "发明人": "inventorNames", "完成人": "inventorNames", "成果完成人": "inventorNames",
    "应用领域": "applicationFields", "可应用领域": "applicationFields",
}

LINK_ALIASES = {
    "个人网站": ("personal_homepage", "个人网站"),
    "个人主页": ("personal_homepage", "个人主页"),
    "官网": ("official_site", "官方网站"),
    "官方网站": ("official_site", "官方网站"),
    "机构网站": ("company_site", "机构网站"),
    "相关链接": ("other", "相关链接"),
}

HARVEST_FIELD_KEYS = {
    "contactName", "contactPhone", "contactEmail", "contactWechat", "contactTitle",
    "maturityLevel", "pricingMode", "inventorNames", "applicationFields",
    "sourceOrgName", "techRoute",
}

_MATURITY_VALUES = {
    **{code: code for code in MATURITY_LEVELS},
    **{label: code for code, label in MATURITY_LABELS.items()},
    "概念": "01_idea",
    "实验室": "02_lab",
    "中试": "03_pilot_ready",
    "可中试": "03_pilot_ready",
    "量产": "05_mass_ready",
    "量产准备": "05_mass_ready",
}

_PRICING_VALUES = {
    "面议": "negotiable",
    "许可": "license",
    "转让": "transfer",
    "合作": "cooperation",
    "其他": "other",
}


def clean_label(label: str) -> str:
    return re.sub(r"[\s（）()【】\[\]-]", "", label or "")


def _alias_map() -> dict[str, str]:
    return {clean_label(name): name for name in list(FIELD_ALIASES) + list(LINK_ALIASES)}


def parse_labeled_line(line: str) -> tuple[str | None, str]:
    text = (line or "").strip()
    if not text:
        return None, ""
    matched = LABEL_RE.match(text)
    aliases = _alias_map()
    if matched:
        cleaned = clean_label(matched.group(1))
        original = aliases.get(cleaned) or matched.group(1).strip()
        return original, matched.group(2).strip()
    original = aliases.get(clean_label(text))
    if original:
        return original, ""
    return None, ""


def map_maturity(value: str) -> str:
    text = (value or "").strip()
    cleaned = clean_label(text)
    if cleaned in _MATURITY_VALUES:
        return _MATURITY_VALUES[cleaned]
    for key, code in _MATURITY_VALUES.items():
        if key and key in text:
            return code
    return ""


def map_pricing(value: str) -> str:
    text = (value or "").strip()
    return _PRICING_VALUES.get(clean_label(text)) or _PRICING_VALUES.get(text, "")


def looks_like_title(line: str) -> bool:
    text = (line or "").strip()
    if not text or len(text) < 2 or len(text) > 80:
        return False
    if EMAIL_RE.search(text) or URL_RE.search(text) or PHONE_RE.fullmatch(text):
        return False
    label, _ = parse_labeled_line(text)
    return label is None


def split_names(value: str) -> list[str]:
    return [item.strip() for item in SPLIT_NAMES_RE.split(value or "") if item.strip()]


def assign_field(target: dict, key: str, value: str) -> None:
    text = (value or "").strip()
    if not text:
        return
    if key == "maturityLevel":
        mapped = map_maturity(text)
        if mapped and not target.get("maturityLevel"):
            target["maturityLevel"] = mapped
        return
    if key == "pricingMode":
        mapped = map_pricing(text)
        if mapped and not target.get("pricingMode"):
            target["pricingMode"] = mapped
        return
    if key == "inventorNames":
        names = split_names(text)
        refs = list(target.get("inventorRefs") or [])
        existing = {item.get("name") for item in refs}
        for name in names:
            if name not in existing:
                refs.append({"name": name, "sortOrder": len(refs)})
                existing.add(name)
        if refs:
            target["inventorRefs"] = refs
        return
    if key == "applicationFields":
        if not target.get("applicationFields"):
            target["applicationFields"] = split_names(text)[:20]
        return
    if key == "techIntro":
        previous = str(target.get("techIntro") or "").strip()
        target["techIntro"] = "\n".join(filter(None, [previous, text])).strip()
        return
    if not target.get(key):
        target[key] = text[:500] if key == "techRoute" else text[:200] if key in {"title", "titleEn"} else text


def append_link(target: dict, label: str, url: str, link_type: str) -> None:
    url = (url or "").strip().rstrip("。.;；,，")
    if not url:
        return
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    links = list(target.get("links") or [])
    if any(item.get("url") == url for item in links):
        return
    links.append({"type": link_type, "label": label, "url": url, "sortOrder": len(links)})
    target["links"] = links


def _line_is_only_contacts(line: str, emails: list[str], phones: list[str], urls: list[str]) -> bool:
    leftover = line
    for item in emails + phones + urls:
        leftover = leftover.replace(item, " ")
    leftover = re.sub(r"[\s:：/]+", "", leftover)
    return leftover == ""


def harvest_fields_from_text(text: str, current: dict | None = None) -> dict:
    """从简介类自由文本拆出联系方式 / 链接，并返回清理后的 techIntro。"""
    target = dict(current or {})
    kept: list[str] = []
    pending: tuple[str, str] | None = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, content = parse_labeled_line(line)
        if label and label in FIELD_ALIASES:
            key = FIELD_ALIASES[label]
            if key not in HARVEST_FIELD_KEYS:
                kept.append(line)
                pending = None
                continue
            if content:
                assign_field(target, key, content)
                pending = None
            else:
                pending = ("field", key)
            continue
        if label and label in LINK_ALIASES:
            link_type, display = LINK_ALIASES[label]
            if content:
                append_link(target, display, content, link_type)
                pending = None
            else:
                pending = ("link", label)
            continue
        if pending:
            kind, key = pending
            pending = None
            if kind == "field":
                assign_field(target, key, line)
            else:
                link_type, display = LINK_ALIASES[key]
                append_link(target, display, line, link_type)
            continue
        emails = EMAIL_RE.findall(line)
        phones = PHONE_RE.findall(line)
        urls = URL_RE.findall(line)
        consumed = False
        if emails and not target.get("contactEmail"):
            target["contactEmail"] = emails[0]
            consumed = True
        if phones and not target.get("contactPhone"):
            target["contactPhone"] = phones[0]
            consumed = True
        for url in urls:
            append_link(target, "相关链接", url, "other")
            consumed = True
        if consumed and _line_is_only_contacts(line, emails, phones, urls):
            continue
        kept.append(line)
    target["techIntro"] = "\n".join(kept).strip()
    return target
