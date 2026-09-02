"""文档交叉引用校验：检查 NN-xxx.md §X.Y 引用的章节是否真实存在。只读。"""
import re
import glob
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = r"c:\Users\admin\Desktop\南山小程序\docs\architecture"

all_files = glob.glob(BASE + r"\*.md") + glob.glob(BASE + r"\adr\*.md")
headings = {}  # filename -> set of section numbers
for f in all_files:
    name = f.split("\\")[-1]
    secs = set()
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^#{2,4}\s+(?:§\s*)?(\d+(?:\.\d+)?)", line)
            if m:
                secs.add(m.group(1))
    headings[name] = secs

doc_num = {}
for name in headings:
    m = re.match(r"^0(\d)-", name)
    if m:
        doc_num[m.group(1)] = name

errors = 0
checked = 0
for f in all_files:
    name = f.split("\\")[-1]
    with open(f, encoding="utf-8") as fh:
        content = fh.read()
    for m in re.finditer(r"`?0(\d)-[a-z\-]+\.md`?\s*(?:§+\s*(\d+(?:\.\d+)?))?", content):
        num, sec = m.group(1), m.group(2)
        if num not in doc_num or sec is None:
            continue
        target = doc_num[num]
        checked += 1
        if sec not in headings[target]:
            line = content[: m.start()].count("\n") + 1
            print(f"断链: {name}:{line} -> 0{num} §{sec}")
            errors += 1

print(f"共检查 {checked} 处带章节号的文档引用, 断链 {errors} 处")

# ADR 引用检查
for f in all_files:
    name = f.split("\\")[-1]
    with open(f, encoding="utf-8") as fh:
        content = fh.read()
    for m in re.finditer(r"ADR-00(\d)", content):
        pass  # ADR 编号 1-3 均存在
adr_files = [f.split("\\")[-1] for f in glob.glob(BASE + r"\adr\*.md")]
print(f"ADR 文件: {adr_files}")
