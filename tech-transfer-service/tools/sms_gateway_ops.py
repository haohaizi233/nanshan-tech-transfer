"""Internal worker/reconciliation and explicitly enabled live acceptance tool.

Run from backend: python tools/sms_gateway_ops.py worker-once
"""

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from modules.security.sms_diagnostics import (
    authorized_live_target,
    config_check,
    diagnose,
    provider_check,
    queue_check,
    risk_snapshot,
)
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
    parser.add_argument(
        "action",
        choices=[
            "worker-once",
            "reconcile",
            "live-test",
            "diagnose",
            "config-check",
            "queue-check",
            "provider-check",
            "risk-check",
        ],
    )
    parser.add_argument("--challenge-id")
    parser.add_argument("--account")
    parser.add_argument("--request-id")
    parser.add_argument("--phone")
    parser.add_argument("--ip")
    parser.add_argument("--device-id")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    if args.action == "config-check":
        print(json.dumps(config_check(), ensure_ascii=False))
    elif args.action == "queue-check":
        print(json.dumps(queue_check(), ensure_ascii=False))
    elif args.action == "provider-check":
        print(json.dumps(provider_check(), ensure_ascii=False))
    elif args.action == "diagnose":
        print(
            json.dumps(
                diagnose(challenge_id=args.challenge_id, request_id=args.request_id, account=args.account),
                ensure_ascii=False,
            )
        )
    elif args.action == "risk-check":
        print(
            json.dumps(
                risk_snapshot(
                    account=args.account,
                    phone=args.phone,
                    ip=args.ip,
                    device_id=args.device_id,
                    task_id=args.challenge_id,
                ),
                ensure_ascii=False,
            )
        )
    elif args.action == "worker-once":
        cleanup_delivery_tasks()
        print(json.dumps({"processed": process_pending_recovery_tasks()}))
    elif args.action == "reconcile":
        if not args.challenge_id:
            parser.error("--challenge-id is required")
        print(json.dumps(reconcile_sms_delivery(str(uuid.UUID(args.challenge_id)))))
    else:
        if not (settings.SMS_LIVE_TEST_ENABLED and args.send and args.account and args.phone):
            parser.error("live-test requires SMS_LIVE_TEST_ENABLED=true, --send, --account and --phone")
        if settings.SMS_PROVIDER != "sendcloud":
            parser.error("live-test requires SendCloud provider")
        if not authorized_live_target(args.account, args.phone):
            parser.error("explicit authorized test target does not match an eligible verified account")
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
    # Database connection internals belong in protected service logs, not CLI JSON.
    logging.getLogger("nanshan.db").disabled = True
    try:
        main()
    except Exception as exc:
        # Never print raw exceptions: connection strings/payloads can contain secrets.
        print(
            json.dumps(
                {
                    "status": "diagnostic_failed",
                    "error_type": type(exc).__name__,
                    "recommended_action": "check_config_schema_and_dependency_connectivity",
                }
            )
        )
        sys.exit(1)
