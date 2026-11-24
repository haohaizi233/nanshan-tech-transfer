"""Email Security Gateway 内部运维与只读诊断工具。

默认全部为只读检查；严禁输出明文验证码、重置链接或恢复凭证；
`check-provider` 绝不发送真实邮件；
`live-test` 必须同时满足 EMAIL_LIVE_TEST_ENABLED=true、--send、--confirm-recipient 且匹配数据库已确权目标。
"""

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from modules.security.email_diagnostics import (
    authorized_live_email_target,
    email_cleanup_expired,
    email_config_check,
    email_explain_failure,
    email_inspect_challenge,
    email_inspect_delivery,
    email_provider_check,
    email_queue_check,
    email_redis_check,
    email_risk_snapshot,
)
from modules.security.email_gateway import (
    email_request_gate,
    reconcile_email_delivery,
)
from modules.security.sms_gateway import (
    SendContext,
    cleanup_delivery_tasks,
    enqueue_recovery_task,
    process_pending_recovery_tasks,
    run_queued_recovery_task,
)


def main():
    parser = argparse.ArgumentParser(description="Email Security Gateway 运维诊断工具")
    parser.add_argument(
        "action",
        choices=[
            "check-config",
            "check-redis",
            "check-provider",
            "inspect-delivery",
            "inspect-challenge",
            "explain-failure",
            "risk-check",
            "queue-check",
            "reconcile",
            "cleanup-expired",
            "worker-once",
            "live-test",
        ],
    )
    parser.add_argument("--challenge-id")
    parser.add_argument("--request-id")
    parser.add_argument("--account")
    parser.add_argument("--email")
    parser.add_argument("--ip")
    parser.add_argument("--device-id")
    parser.add_argument("--code")
    parser.add_argument("--channel", choices=["email_otp", "email_link"], default="email_otp")
    parser.add_argument("--apply", action="store_true", help="仅用于 cleanup-expired 执行实际清理")
    parser.add_argument("--send", action="store_true", help="仅用于 live-test 显式授权真实单次投递")
    parser.add_argument("--confirm-recipient", help="live-test 再次确认目标收件人邮箱")
    args = parser.parse_args()

    if args.action == "check-config":
        print(json.dumps(email_config_check(), ensure_ascii=False, indent=2))
    elif args.action == "check-redis":
        print(json.dumps(email_redis_check(), ensure_ascii=False, indent=2))
    elif args.action == "check-provider":
        print(json.dumps(email_provider_check(), ensure_ascii=False, indent=2))
    elif args.action == "inspect-delivery":
        print(
            json.dumps(
                email_inspect_delivery(challenge_id=args.challenge_id, request_id=args.request_id),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.action == "inspect-challenge":
        print(
            json.dumps(
                email_inspect_challenge(challenge_id=args.challenge_id, account=args.account),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.action == "explain-failure":
        if not args.code:
            parser.error("--code is required for explain-failure")
        print(json.dumps(email_explain_failure(args.code), ensure_ascii=False, indent=2))
    elif args.action == "risk-check":
        print(
            json.dumps(
                email_risk_snapshot(
                    account=args.account,
                    email=args.email,
                    ip=args.ip,
                    device_id=args.device_id,
                    task_id=args.challenge_id,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.action == "queue-check":
        print(json.dumps(email_queue_check(), ensure_ascii=False, indent=2))
    elif args.action == "reconcile":
        if not args.challenge_id:
            parser.error("--challenge-id is required for reconcile")
        print(json.dumps(reconcile_email_delivery(str(uuid.UUID(args.challenge_id))), ensure_ascii=False, indent=2))
    elif args.action == "cleanup-expired":
        print(json.dumps(email_cleanup_expired(dry_run=not args.apply), ensure_ascii=False, indent=2))
    elif args.action == "worker-once":
        cleanup_delivery_tasks()
        print(json.dumps({"processed": process_pending_recovery_tasks()}, ensure_ascii=False))
    elif args.action == "live-test":
        if not (
            settings.EMAIL_LIVE_TEST_ENABLED
            and settings.EMAIL_ENABLED
            and args.send
            and args.account
            and args.email
            and args.confirm_recipient
        ):
            parser.error(
                "live-test requires EMAIL_LIVE_TEST_ENABLED=true, EMAIL_ENABLED=true, --send, "
                "--account, --email, and --confirm-recipient"
            )
        if args.email.strip().lower() != args.confirm_recipient.strip().lower():
            parser.error("--confirm-recipient must match --email")
        if (settings.EMAIL_PROVIDER or "").strip().lower() not in {"smtp", "tencent"}:
            parser.error("live-test requires EMAIL_PROVIDER=smtp or tencent")
        if not authorized_live_email_target(args.account, args.email):
            parser.error("explicit authorized target does not match an eligible verified email account")

        cid = str(uuid.uuid4())
        ctx = SendContext("127.0.0.1", "operator-email-live-test", str(uuid.uuid4()))
        email_request_gate(ctx, args.account, email=args.email, purpose="password_recovery")
        enqueue_recovery_task(args.account, args.channel, cid, ctx)
        run_queued_recovery_task(cid)
        print(
            json.dumps(
                {
                    "challenge_id": cid,
                    "channel": args.channel,
                    "message": "Inspect internal delivery state via inspect-delivery; acceptance is not delivery.",
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    logging.getLogger("nanshan.db").disabled = True
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "diagnostic_failed",
                    "error_type": type(exc).__name__,
                    "recommended_action": "check_config_schema_and_dependency_connectivity",
                },
                ensure_ascii=False,
            )
        )
        sys.exit(1)
