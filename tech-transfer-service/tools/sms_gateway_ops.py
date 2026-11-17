"""Internal worker/reconciliation and explicitly enabled live acceptance tool.

Run from backend: python tools/sms_gateway_ops.py worker-once
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from modules.security.sms_gateway import (
    SendContext,
    cleanup_delivery_tasks,
    enqueue_recovery_task,
    process_pending_recovery_tasks,
    reconcile_sms_delivery,
    request_gate,
    run_queued_recovery_task,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["worker-once", "reconcile", "live-test"])
    parser.add_argument("--challenge-id")
    parser.add_argument("--account")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    if args.action == "worker-once":
        cleanup_delivery_tasks()
        print(json.dumps({"processed": process_pending_recovery_tasks()}))
    elif args.action == "reconcile":
        if not args.challenge_id:
            parser.error("--challenge-id is required")
        print(json.dumps(reconcile_sms_delivery(str(uuid.UUID(args.challenge_id)))))
    else:
        if not (settings.SMS_LIVE_TEST_ENABLED and args.send and args.account):
            parser.error("live-test requires SMS_LIVE_TEST_ENABLED=true, --send and --account")
        if settings.SMS_PROVIDER != "sendcloud":
            parser.error("live-test requires SendCloud provider")
        cid = str(uuid.uuid4())
        ctx = SendContext("127.0.0.1", "operator-live-test", str(uuid.uuid4()))
        request_gate(ctx, args.account)
        enqueue_recovery_task(args.account, "sms", cid, ctx)
        run_queued_recovery_task(cid)
        print(
            json.dumps(
                {"challenge_id": cid, "message": "Inspect internal delivery state; request acceptance is not delivery."}
            )
        )


if __name__ == "__main__":
    main()
