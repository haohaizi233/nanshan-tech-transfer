import argparse
import hashlib
import inspect
import json
from pathlib import Path
import sys
import time
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from db import get_cursor
from modules.ai.chat_runner import StreamError, post_agent, validate_result


def diagnose(turn_id, probe=False):
    report = {
        "validatorFingerprint": hashlib.sha256(inspect.getsource(validate_result).encode()).hexdigest()[:12],
        "acceptsTwentyEvaluationCards": False,
    }
    sample = {"success": True, "intent": "evaluate_achievement", "message": "test", "data": [
        {"card_type": "achievement", "id": number} for number in range(1, 21)
    ]}
    try:
        validate_result(sample)
        report["acceptsTwentyEvaluationCards"] = True
    except StreamError:
        pass
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT to_jsonb(t) AS entry FROM ai_chat_turn t WHERE turn_id = %s ORDER BY id DESC LIMIT 2",
            (turn_id,),
        )
        rows = cursor.fetchall()
    if len(rows) != 1:
        report["lookup"] = "not_found" if not rows else "ambiguous_turn_id"
        return report
    turn = rows[0]["entry"]
    report["turn"] = {key: turn.get(key) for key in (
        "turn_id", "status", "stage", "stage_seq", "execution_mode", "error_code",
        "error_status", "created_at", "updated_at", "completed_at",
    )}
    report["runningSource"] = "This CLI reads files on disk; it does not prove an existing worker reloaded them."
    if not probe:
        return report
    if turn.get("user_message", "").strip() not in ("/评估", "评估成果"):
        report["probe"] = "refused_non_picker_command"
        return report
    stages = []
    started = time.monotonic()
    try:
        result = post_agent(
            settings.AI_CHAT_STREAM_URL, settings.AI_INTERNAL_SERVICE_KEY,
            {"message": "/评估", "exclude_owner_user_id": turn["user_id"],
             "executionId": "diagnose-picker", "context": {"schemaVersion": 1, "generation": turn.get("generation", 0), "queryPlan": {}, "cards": [], "messages": []}},
            15, lambda stage, sequence: stages.append({"stage": stage, "sequence": sequence}),
        )
        report["probe"] = {"status": "ok", "intent": result.get("intent"), "cards": len(result.get("data") or [])}
    except StreamError as error:
        report["probe"] = {"status": "protocol_error", "reason": str(error)}
    except urllib.error.HTTPError as error:
        report["probe"] = {"status": "agent_http_error", "httpStatus": error.code}
    except Exception as error:
        report["probe"] = {"status": "transport_error", "exceptionType": type(error).__name__}
    report["probeStages"] = stages
    report["probeElapsedMs"] = round((time.monotonic() - started) * 1000)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only AI picker diagnostics; never replay arbitrary commands.")
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--probe-agent", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(diagnose(arguments.turn_id, arguments.probe_agent), ensure_ascii=False, default=str, indent=2))
