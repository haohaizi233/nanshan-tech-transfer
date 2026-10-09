#!/usr/bin/env python3
"""Verify all modified Python files parse correctly."""
import ast
import sys

files = [
    "/Users/mac/Desktop/南山小程序/nanshan-ai-agent/app/reranker.py",
    "/Users/mac/Desktop/南山小程序/nanshan-ai-agent/app/main.py",
    "/Users/mac/Desktop/南山小程序/nanshan-ai-agent/app/router.py",
    "/Users/mac/Desktop/南山小程序/nanshan-ai-agent/app/database.py",
    "/Users/mac/Desktop/南山小程序/nanshan-ai-agent/app/llm_client.py",
    "/Users/mac/Desktop/南山小程序/tech-transfer-service/db.py",
    "/Users/mac/Desktop/南山小程序/tech-transfer-service/app.py",
    "/Users/mac/Desktop/南山小程序/tech-transfer-service/routes/file.py",
    "/Users/mac/Desktop/南山小程序/tech-transfer-service/modules/identity/service.py",
    "/Users/mac/Desktop/南山小程序/tech-transfer-service/test_core_units.py",
    "/Users/mac/Desktop/南山小程序/tech-transfer-service/_smoke_test.py",
]

ok = 0
for f in files:
    try:
        ast.parse(open(f).read(), filename=f)
        print(f"OK: {f.split('/')[-1]}")
        ok += 1
    except SyntaxError as e:
        print(f"FAIL: {f.split('/')[-1]}: {e}")

print(f"\n{ok}/{len(files)} files OK")
if ok < len(files):
    sys.exit(1)