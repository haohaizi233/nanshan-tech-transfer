"""Syntax check helper for admin-edit-log feature files."""
import ast

FILES = [
    "app.py",
    "routes/admin_changes.py",
    "modules/admin/edit_log.py",
    "modules/admin/service.py",
]
for f in FILES:
    ast.parse(open(f, encoding="utf-8").read())
    print("OK", f)
