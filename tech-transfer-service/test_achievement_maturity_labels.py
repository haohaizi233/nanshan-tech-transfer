"""Maturity enum should persist and display Chinese labels, not raw codes."""
from pathlib import Path

from modules.achievement.maturity import resolve_maturity_desc


def main():
    assert resolve_maturity_desc("01_idea") == "概念阶段"
    assert resolve_maturity_desc("02_lab", None) == "实验室验证"
    assert resolve_maturity_desc("02_lab", "02_lab") == "实验室验证"
    assert resolve_maturity_desc("03_pilot_ready", "可进入中试") == "可进入中试"
    assert resolve_maturity_desc("04_pilot_done", "中试完成") == "中试完成"

    source = Path("modules/achievement/service.py").read_text(encoding="utf-8")
    assert 'fields["maturity_desc"] = MATURITY_LABELS.get(fields["maturity_level"])' in source
    assert '"status": row.get("status")' in source
    assert '"version": row.get("version")' in source
    print("PASS: achievement maturity codes resolve to Chinese labels")


if __name__ == "__main__":
    main()
