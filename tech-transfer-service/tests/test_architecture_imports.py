"""P3-7 架构依赖治理棘轮测试（AST 静态导入扫描）。

原则：
- 冻结当前已知历史例外，不要求一次性清零；
- 严禁新增任何模块间循环依赖；
- 严禁新增任何跨模块导入 `_` 私有函数；
- 严禁 `modules.*` 反向导入 `routes.*`，或 `core.*` 反向导入 `modules.*` / `routes.*`。
"""

from __future__ import annotations

import ast
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = SERVICE_ROOT / "modules"

# 历史已知 2-节点循环依赖（只允许减少，不允许新增）
KNOWN_2_CYCLES = {
    ("achievement", "admin"),
}

# 历史已知跨模块私有导入（只允许减少，不允许新增）
KNOWN_CROSS_PRIVATE_IMPORTS = {
    ("admin", "modules.achievement.service._parse_upsert_body"),
    ("admin", "modules.achievement.service._sync_inventors"),
    ("admin", "modules.achievement.service._validate_refs"),
    ("admin", "modules.cooperation.service._release_target_slot"),
    ("admin", "modules.cooperation.service._reserve_target_slot"),
    ("admin", "modules.demand.service._load_tags"),
    ("admin", "modules.demand.service._parse_upsert_body"),
    ("admin", "modules.demand.service._resolve_name_refs"),
    ("admin", "modules.demand.service._sync_tags"),
    ("admin", "modules.demand.service._validate_refs"),
}


def test_architecture_import_ratchet():
    mod_names = {d.name for d in MODULES_DIR.iterdir() if d.is_dir() and d.name != "__pycache__"}
    edges: set[tuple[str, str]] = set()
    cross_private: set[tuple[str, str]] = set()
    reverse_violations: list[str] = []

    for py in SERVICE_ROOT.rglob("*.py"):
        if any(part in py.parts for part in ("tests", "__pycache__", ".venv")):
            continue
        rel = py.relative_to(SERVICE_ROOT)
        layer = rel.parts[0]
        src_mod = rel.parts[1] if layer == "modules" and len(rel.parts) >= 2 else None
        tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            parts = node.module.split(".")
            if layer == "core" and parts[0] in ("modules", "routes"):
                reverse_violations.append(f"{rel}:{node.lineno} -> {node.module}")
            if layer == "modules" and parts[0] == "routes":
                reverse_violations.append(f"{rel}:{node.lineno} -> {node.module}")
            if src_mod in mod_names and parts[0] == "modules" and len(parts) >= 2:
                dst_mod = parts[1]
                if dst_mod != src_mod:
                    edges.add((src_mod, dst_mod))
                    for alias in node.names:
                        if alias.name.startswith("_"):
                            cross_private.add((src_mod, f"{node.module}.{alias.name}"))

    assert reverse_violations == [], f"禁止反向层依赖: {reverse_violations}"

    adj: dict[str, set[str]] = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
    cycles = {(a, b) for a in adj for b in adj.get(a, ()) if a < b and a in adj.get(b, ())}
    new_cycles = cycles - KNOWN_2_CYCLES
    assert not new_cycles, f"发现新增模块循环依赖: {sorted(new_cycles)}"

    new_private = cross_private - KNOWN_CROSS_PRIVATE_IMPORTS
    assert not new_private, f"发现新增跨模块私有导入: {sorted(new_private)}"
