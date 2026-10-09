"""独立进程运行 AI worker，不加载 FastAPI、不占用 8787。

  python tools/run_ai_worker.py --once
  python tools/run_ai_worker.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.ai import worker  # noqa: E402
from modules.ai.provider import configured  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the tech-transfer AI worker")
    parser.add_argument("--once", action="store_true", help="process at most one queued task then exit")
    parser.add_argument("--interval", type=float, default=3.0, help="idle poll seconds")
    args = parser.parse_args()

    if not configured():
        print("AI worker idle: set AI_PROVIDER_BASE to the remote Hermes OpenAI URL")
        print("  example: AI_PROVIDER_BASE=http://<hermes-host>:8642/v1")
        print("  WeCom Bot ID/Secret stay on the Hermes gateway; this process only uses HTTP.")
        return 2
    try:
        if args.once:
            status = worker.process_one()
            print(f"ai worker once={status}")
            return 0 if status in {"idle", "succeeded"} else 1
        print("ai worker polling queued tasks (Ctrl+C to stop)")
        while True:
            status = worker.process_one()
            if status == "idle":
                time.sleep(max(0.5, args.interval))
            elif status == "unconfigured":
                print("AI_PROVIDER_BASE missing; exit")
                return 2
    except KeyboardInterrupt:
        print("ai worker stopped")
        return 0
    finally:
        worker.close()


if __name__ == "__main__":
    sys.exit(main())
