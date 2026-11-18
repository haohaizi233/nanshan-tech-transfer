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
            "direct-send",
            "diagnose-phone",
        ],
    )
    parser.add_argument("--challenge-id")
    parser.add_argument("--account")
    parser.add_argument("--request-id")
    parser.add_argument("--phone")
    parser.add_argument("--ip")
    parser.add_argument("--device-id")
    parser.add_argument("--code")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    if args.action == "diagnose-phone":
        if not args.phone:
            parser.error("--phone is required for diagnose-phone")
        from modules.security.provider import get_sms_provider

        provider = get_sms_provider()
        if not hasattr(provider, "query_status"):
            parser.error("Provider does not support status query")
        clean_phone = args.phone.strip()
        if clean_phone.startswith("+86"):
            clean_phone = clean_phone[3:]
        # 查询最近 3 天的投递记录
        import hashlib
        import urllib.parse
        import urllib.request

        payload = {
            "smsUser": provider.sms_user,
            "days": "3",
            "start": "0",
            "limit": "50",
        }
        sign_raw = "&".join(f"{k}={payload[k]}" for k in sorted(payload))
        sign_str = f"{provider.sms_key}&{sign_raw}&{provider.sms_key}"
        payload["signature"] = hashlib.sha256(sign_str.encode()).hexdigest()
        req = urllib.request.Request(
            provider.STATUS_URL,
            data=urllib.parse.urlencode(payload).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            all_records = data.get("info", {}).get("voList", []) if data.get("result") else []
            phone_records = [r for r in all_records if str(r.get("receiver", "")).endswith(clean_phone[-11:])]
            if not phone_records:
                print(
                    json.dumps(
                        {
                            "phone": clean_phone,
                            "records_found": 0,
                            "message": "近3天在SendCloud未找到该号码的投递记录；请确认是否曾通过API发起发送",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                summary = []
                for r in phone_records:
                    status_code = r.get("statusCode")
                    send_log = r.get("sendLog")
                    diag = (
                        "投递成功"
                        if status_code == 200
                        else "运营商通道/签名拦截(4121)，需联系SendCloud工单报备"
                        if str(send_log) == "4121"
                        else f"投递失败({status_code}/{send_log})"
                    )
                    summary.append(
                        {
                            "request_time": r.get("requestTime"),
                            "status": r.get("status"),
                            "status_code": status_code,
                            "send_log": send_log,
                            "template_id": r.get("templateId"),
                            "diagnosis": diag,
                        }
                    )
                print(
                    json.dumps(
                        {
                            "phone": clean_phone,
                            "records_found": len(phone_records),
                            "latest": summary[0] if summary else None,
                            "all_recent": summary,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        except Exception as e:
            print(json.dumps({"error": str(e), "message": "查询SendCloud状态失败"}, ensure_ascii=False))
    elif args.action == "direct-send":
        if not args.phone:
            parser.error("--phone is required for direct-send")
        from modules.security.provider import get_sms_provider

        provider = get_sms_provider()
        test_code = args.code or "123456"
        task_id = args.challenge_id or str(uuid.uuid4())
        receipt = provider.send_task(args.phone, test_code, "bind_phone", 300, send_request_id=task_id)
        print(
            json.dumps(
                {
                    "status": "accepted" if receipt.accepted else "failed",
                    "provider_ids": list(receipt.provider_ids),
                    "request_id": receipt.request_id,
                    "message": "SendCloud request accepted. Use reconcile or status/query to verify downstream delivery.",
                },
                ensure_ascii=False,
            )
        )
    elif args.action == "config-check":
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
