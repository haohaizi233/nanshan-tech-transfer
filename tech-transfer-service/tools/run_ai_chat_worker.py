"""Run durable chat workers independently of the evaluation worker."""

import argparse
import concurrent.futures
import json
import signal
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from db import close_pool, get_cursor
from modules.ai import chat_runs
from modules.ai.chat_runner import execute_run, private_opener


def probe_agent():
    parsed = urlparse(settings.AI_CHAT_STREAM_URL)
    url = f"{parsed.scheme}://{parsed.netloc}/internal/ai/ready"
    try:
        request = urllib.request.Request(url, headers={"X-AI-Service-Key": settings.AI_INTERNAL_SERVICE_KEY})
        with private_opener().open(request, timeout=2) as response:
            payload = json.loads(response.read(4096))
            return (
                response.status == 200
                and isinstance(payload, dict)
                and payload.get("schemaVersion") == 1
                and payload.get("capacity") == settings.AI_CHAT_GLOBAL_SLOTS
                and type(payload.get("executionBudgetSeconds")) in (int, float)
                and payload["executionBudgetSeconds"] >= min(55, settings.AI_CHAT_EXECUTION_SECONDS)
                and payload.get("modelConfigured") is True
            )
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Run durable chat execution leases and recovery")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--reaper-only", action="store_true")
    args = parser.parse_args()
    if args.health:
        status = chat_runs.health_status()
        print(json.dumps(status))
        return 0 if all(status.values()) else 2
    if not args.reaper_only and not chat_runs.configuration_ready():
        print("Chat worker configuration unavailable: private stream URL and service key are required")
        return 2
    if settings.AI_CHAT_RENEW_SECONDS >= settings.AI_CHAT_LEASE_SECONDS:
        print("Renew interval must be shorter than lease duration")
        return 2
    stop = threading.Event()

    def shutdown(*_args):
        stop.set()

    for signal_id in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_id, shutdown)
    worker_id = str(uuid.uuid4())
    if not args.reaper_only:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO ai_chat_execution_slot(slot_id) SELECT generate_series(1, %s) ON CONFLICT DO NOTHING",
                (settings.AI_CHAT_GLOBAL_SLOTS,),
            )
    futures = set()
    last_housekeeping = 0.0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=settings.AI_CHAT_GLOBAL_SLOTS) as pool:
            while not stop.is_set():
                for future in list(futures):
                    if future.done():
                        print(f"chat execution status={future.result()}")
                        futures.remove(future)
                now = time.monotonic()
                if now - last_housekeeping >= settings.AI_CHAT_REAP_SECONDS:
                    chat_runs.reap_runs()
                    if not args.reaper_only:
                        chat_runs.heartbeat_worker(worker_id, probe_agent())
                    last_housekeeping = now
                if not args.reaper_only and len(futures) < settings.AI_CHAT_GLOBAL_SLOTS:
                    run = chat_runs.claim_one(worker_id)
                    if run:
                        futures.add(pool.submit(execute_run, run))
                if args.once:
                    statuses = []
                    for future in futures:
                        statuses.append(future.result())
                    print(f"chat worker once={','.join(statuses) if statuses else 'idle'}")
                    return 0 if all(status == "succeeded" for status in statuses) else 1
                stop.wait(0.5)
        return 0
    finally:
        if not args.reaper_only:
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM ai_chat_worker WHERE worker_id = %s", (worker_id,))
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
