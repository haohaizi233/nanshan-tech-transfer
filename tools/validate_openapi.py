"""openapi.yaml 结构自检：YAML 语法 / 路径重复 / $ref 引用 / 必填字段。只读校验，不安装任何依赖。"""
import sys
import re
import yaml

PATH = r"c:\Users\admin\Desktop\南山小程序\docs\architecture\openapi.yaml"

errors = []
warnings = []

with open(PATH, encoding="utf-8") as f:
    raw = f.read()

doc = yaml.safe_load(raw)
print(f"[1] YAML 语法解析: OK ({len(raw.splitlines())} 行)")

# 2. 顶层必填字段
for key in ["openapi", "info", "servers", "tags", "paths", "components"]:
    if key not in doc:
        errors.append(f"缺少顶层字段: {key}")
print(f"[2] 顶层字段: openapi={doc.get('openapi')}, info.title={doc['info']['title']}, paths={len(doc['paths'])}, schemas={len(doc['components'].get('schemas', {}))}, responses={len(doc['components'].get('responses', {}))}, parameters={len(doc['components'].get('parameters', {}))}, securitySchemes={list(doc['components'].get('securitySchemes', {}).keys())}")

# 3. 路径重复（YAML 解析层面重复键会被静默覆盖，需从原始文本检测）
path_re = re.compile(r'^  (/[A-Za-z0-9_{}/\-]+):')
seen = {}
for i, line in enumerate(raw.splitlines(), 1):
    m = path_re.match(line)
    if m:
        p = m.group(1)
        if p in seen:
            errors.append(f"路径重复: {p} (行 {seen[p]} 与 行 {i})")
        seen[p] = i
print(f"[3] 路径重复检测: {len(seen)} 个路径, {'无重复' if len(seen) == len([l for l in raw.splitlines() if path_re.match(l)]) else '发现重复!'}")

# 4. $ref 引用解析
ref_re = re.compile(r"\$ref:\s*'#/([\w/]+)'")
refs = set(ref_re.findall(raw))
def resolve(node, parts):
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return False
        node = node[p]
    return True
for ref in refs:
    if not resolve(doc, ref.split("/")):
        errors.append(f"$ref 引用不存在: #/{ref}")
print(f"[4] $ref 引用: {len(refs)} 个唯一引用, 全部可解析" if not any('$ref' in e for e in errors) else "[4] $ref 存在断链!")

# 5. 每个 path+method 的基本结构
methods = {"get", "post", "put", "patch", "delete"}
op_count = 0
for path, item in doc["paths"].items():
    for m in methods & set(item.keys()):
        op = item[m]
        op_count += 1
        if "summary" not in op:
            errors.append(f"{m.upper()} {path}: 缺少 summary")
        if "responses" not in op:
            errors.append(f"{m.upper()} {path}: 缺少 responses")
        elif "200" not in op["responses"] and "201" not in op["responses"] and "202" not in op["responses"] and "204" not in op["responses"]:
            errors.append(f"{m.upper()} {path}: responses 缺少 2xx")
print(f"[5] 操作数: {op_count} 个 path+method, summary/responses 检查完成")

# 6. 请求体 required 检查（POST/PATCH/PUT 应有 requestBody 或明确说明）
for path, item in doc["paths"].items():
    for m in {"post", "patch", "put"} & set(item.keys()):
        if "requestBody" not in item[m]:
            warnings.append(f"{m.upper()} {path}: 无 requestBody（请确认设计如此）")

# 7. 与 06 文档路径对齐（抽取 06 中列出的核心路径）
doc06_expect = [
    "/auth/bootstrap", "/auth/refresh", "/auth/logout",
    "/me", "/me/profile", "/me/demands", "/me/achievements",
    "/me/favorites", "/me/cooperations",
    "/achievements", "/achievements/{id}", "/achievements/{id}/submit", "/achievements/{id}/offline",
    "/achievements/{id}/evaluations", "/achievements/{id}/patents", "/achievements/{id}/patents/{patentId}",
    "/demands", "/demands/{id}", "/demands/{id}/submit", "/demands/{id}/cancel", "/demands/{id}/close",
    "/demands/{id}/matches",
    "/favorites/{targetType}/{targetId}",
    "/cooperations", "/cooperations/{id}", "/cooperations/{id}/accept", "/cooperations/{id}/reject",
    "/cooperations/{id}/confirm", "/cooperations/{id}/cancel", "/cooperations/{id}/complete",
    "/cooperations/{id}/events",
    "/search", "/ai/match-tasks", "/ai/match-tasks/{taskId}", "/ai/evaluation-tasks", "/ai/evaluation-tasks/{taskId}",
    "/capital/platforms", "/capital/platforms/{id}", "/capital/investment-organizations",
    "/capital/financial-organizations", "/capital/service-organizations",
    "/patents", "/patents/{id}",
    "/uploads/presign", "/uploads/{uploadId}/complete",
    "/admin/achievements/review-queue", "/admin/achievements/{id}/approve", "/admin/achievements/{id}/reject",
    "/admin/demands/review-queue", "/admin/demands/{id}/approve", "/admin/demands/{id}/reject",
    "/admin/audit-logs",
]
missing = [p for p in doc06_expect if p not in doc["paths"]]
if missing:
    errors.append(f"06 文档要求但 yaml 缺失的路径: {missing}")
extra = [p for p in doc["paths"] if p not in doc06_expect]
if extra:
    errors.append(f"yaml 存在但 06 文档未收录的路径: {extra}")
print(f"[6] 与 06 文档路径对齐: {len(doc06_expect) - len(missing)}/{len(doc06_expect)} 覆盖, 反向多出 {len(extra)} 条")

print()
if warnings:
    print("警告:")
    for w in warnings:
        print("  W:", w)
if errors:
    print("错误:")
    for e in errors:
        print("  E:", e)
    sys.exit(1)
print("== 校验通过 ==")
