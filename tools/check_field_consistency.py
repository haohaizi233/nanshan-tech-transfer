"""05 数据模型 ↔ openapi.yaml 字段一致性抽查（camelCase 自动映射）。只读。"""
import io
import re
import sys

import yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = r"c:\Users\admin\Desktop\南山小程序\docs\architecture"
doc = yaml.safe_load(open(BASE + r"\openapi.yaml", encoding="utf-8"))
content = open(BASE + r"\05-data-model-design.md", encoding="utf-8").read()


def camel(s):
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def check(schema_name, section_re):
    m = re.search(section_re + r".*?(?=\n###|\n##|\Z)", content, re.S)
    fields_05 = set(re.findall(r"^\|\s*([a-z_0-9]+)\s*\|", m.group(0), re.M)) if m else set()
    sch = doc["components"]["schemas"][schema_name]
    props = set()
    stack = [sch]
    while stack:
        s = stack.pop()
        if "allOf" in s:
            stack.extend(s["allOf"])
        props |= set(s.get("properties", {}).keys())
    cam05 = {camel(f) for f in fields_05}
    allow = {"isMine", "version", "id", "createdAt", "updatedAt", "deletedAt"}
    only_yaml = props - cam05 - allow
    only_md = cam05 - props - allow
    print(f"{schema_name}: yaml {len(props)} 字段 / 05 {len(fields_05)} 字段")
    if only_yaml:
        print("  仅在yaml(需05补充或为输出附加):", sorted(only_yaml))
    if only_md:
        print("  仅在05(API无输出,需确认):", sorted(only_md))


check("AchievementSummary", r"### 3\.1 .achievement.")
check("DemandSummary", r"### 5\.1 .demand.")
check("PatentSummary", r"### 4\.1 .patent.")
check("CooperationIntent", r"### 6\.2 .cooperation_intent.")
print("--- 字段一致性抽查完成 ---")
