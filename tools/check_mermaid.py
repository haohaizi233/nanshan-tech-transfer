"""Mermaid 图基本语法检查：图类型声明、引号配对。只读。"""
import glob
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

files = (
    glob.glob(r"c:\Users\admin\Desktop\南山小程序\docs\architecture\*.md")
    + glob.glob(r"c:\Users\admin\Desktop\南山小程序\docs\architecture\adr\*.md")
)
total = 0
issues = 0
for f in files:
    content = open(f, encoding="utf-8").read()
    name = f.split("\\")[-1]
    for m in re.finditer(r"```mermaid\n(.*?)```", content, re.S):
        total += 1
        block = m.group(1)
        first = block.strip().splitlines()[0]
        if not re.match(r"^(flowchart|stateDiagram|erDiagram|sequenceDiagram|classDiagram|graph)", first):
            print(f"{name}: 未知图类型 [{first}]")
            issues += 1
        if block.count('"') % 2 != 0:
            print(f"{name}: 引号不配对")
            issues += 1
        # erDiagram: 关系行基本形态
        if first.startswith("erDiagram"):
            for line in block.splitlines():
                s = line.strip()
                if not s or s.startswith("erDiagram") or s.startswith("%%"):
                    continue
                if re.match(r"^[A-Za-z_]+\s+(\|\|--\|\||\|\|--o\{|o--o\{|o--\|\||\}o--\|\||\}o--o\{)", s):
                    continue
                if not re.match(r"^[A-Za-z_]+\s+\S+\s+[A-Za-z_]+", s):
                    print(f"{name}: 可疑ER行: {s[:70]}")
                    issues += 1
print(f"共 {total} 个 mermaid 图块, 问题 {issues} 处")
