"""大模型输入/输出落盘。

- logs/llm-YYYY-MM-DD.jsonl  一行一条，给程序扫
- logs/llm-YYYY-MM-DD.log    分段排版，给人读
控制台同步打一份短摘要。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock, Thread

try:
    import fcntl
except ImportError:
    fcntl = None

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_lock = Lock()
_BODY_LIMIT = 4000
_RAW_PREVIEW = 1200
_SYSTEM_PREVIEW = 80
_log_queue = queue.Queue(maxsize=512)
_worker_lock = Lock()
_worker_started = False
_logger = logging.getLogger(__name__)
_last_prune_day = None
_LOG_RETENTION_DAYS = 14
_MAX_LOG_BYTES = 20 * 1024 * 1024
_LOG_BACKUPS = 3


def _trim(value, limit: int = _BODY_LIMIT):
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            text = str(value)
    if len(text) <= limit:
        return value if isinstance(value, (dict, list)) else text
    if isinstance(value, str):
        return text[:limit] + "…"
    return text[:limit] + "…"


def parse_error_fields(body: str) -> dict:
    """从上游错误正文抽出常见字段，方便按状态码对照。"""
    text = (body or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return {"raw": _trim(text, 800)}
    if not isinstance(payload, dict):
        return {"raw": _trim(payload, 800)}
    fields = {}
    for key in (
        "error", "message", "detail", "code", "type", "status",
        "status_code", "object", "param",
    ):
        if key in payload:
            fields[key] = _trim(payload[key], 800)
    if not fields:
        fields = {key: _trim(val, 400) for key, val in list(payload.items())[:12]}
    return fields


def _pretty(value) -> str:
    if value is None:
        return "（空）"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "（空）"
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return text
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        return text
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)


def _extract_json_object(text: str):
    raw = (text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
    raw = re.sub(r"^Here's a thinking process:.*?(?=\{)", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, TypeError):
        pass
    decoder = json.JSONDecoder()
    found = None
    for match in re.finditer(r"\{", raw):
        try:
            parsed, _ = decoder.raw_decode(raw, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            found = parsed
    return found


def _infer_stage(system_text: str) -> str:
    text = system_text or ""
    if "重排器" in text or "候选结果进行相关性排序" in text:
        return "重排"
    if "JSON 格式转换器" in text or "JSON输出器" in text or "JSON 输出器" in text:
        return "JSON兜底"
    if "参数解析器" in text:
        return "意图解析"
    return "调用"


def summarize_messages(messages) -> dict:
    user = ""
    system = ""
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "")
        if role == "user" and not user:
            user = content.strip()
        elif role == "system" and not system:
            system = content.strip()
    first_line = system.splitlines()[0].strip() if system else ""
    if len(first_line) > _SYSTEM_PREVIEW:
        first_line = first_line[:_SYSTEM_PREVIEW] + "…"
    return {
        "user": user,
        "system_preview": first_line,
        "system_chars": len(system),
        "stage": _infer_stage(system),
    }


def enrich_event(event: dict) -> dict:
    src = dict(event or {})
    messages = ((src.get("input") or {}) if isinstance(src.get("input"), dict) else {}).get("messages")
    summary = summarize_messages(messages)
    output = src.get("output") or ""
    parsed = _extract_json_object(output) if isinstance(output, str) else (
        output if isinstance(output, dict) else None
    )
    usage = src.get("usage") if isinstance(src.get("usage"), dict) else {}
    src["stage"] = src.get("stage") or summary["stage"]
    src["user"] = src.get("user") or summary["user"]
    src["system_preview"] = src.get("system_preview") or summary["system_preview"]
    src["system_chars"] = src.get("system_chars") or summary["system_chars"]
    if parsed is not None and "output_json" not in src:
        src["output_json"] = parsed
    src["prompt_tokens"] = usage.get("prompt_tokens") or usage.get("input_tokens")
    src["completion_tokens"] = usage.get("completion_tokens") or usage.get("output_tokens")
    src["total_tokens"] = usage.get("total_tokens")
    src["elapsed"] = usage.get("total_time")
    return src


def format_llm_log_text(event: dict, include_raw: bool = True) -> str:
    rec = enrich_event(event)
    ok = rec.get("ok")
    status_label = "成功" if ok else "失败"
    usage_bits = []
    if rec.get("elapsed") is not None:
        usage_bits.append(f"耗时 {rec['elapsed']}s")
    if rec.get("prompt_tokens") is not None or rec.get("completion_tokens") is not None:
        usage_bits.append(
            f"tokens 输入 {rec.get('prompt_tokens') or 0} + 输出 {rec.get('completion_tokens') or 0}"
            + (f" = {rec['total_tokens']}" if rec.get("total_tokens") is not None else "")
        )
    header = [
        "=" * 72,
        f"时间 {rec.get('ts') or '-'}    {status_label}    {rec.get('stage') or '调用'}"
        f"    HTTP {rec.get('status') if rec.get('status') is not None else '-'}"
        f"    尝试 {rec.get('attempt') or 1}/{rec.get('attempts') or 1}",
        f"模型 {rec.get('model') or '-'}",
    ]
    if usage_bits:
        header.append("    ".join(usage_bits))
    lines = header + ["-" * 72, "用户", rec.get("user") or "（空）"]
    if rec.get("system_preview"):
        lines.extend([
            "",
            "系统提示",
            f"{rec['system_preview']}  （共 {rec.get('system_chars') or 0} 字）",
        ])
    if rec.get("output_json") is not None:
        lines.extend(["-" * 72, "模型解析", _pretty(rec["output_json"])])
    elif rec.get("ok") and rec.get("output"):
        lines.extend(["-" * 72, "模型输出", _pretty(rec["output"])])
    if not rec.get("ok"):
        error = rec.get("error") or {}
        lines.extend([
            "-" * 72,
            f"失败原因 {rec.get('reason') or error.get('type') or '-'}",
            _pretty(error) if error else (rec.get("reason") or "未知错误"),
        ])
    raw = rec.get("output") if isinstance(rec.get("output"), str) else ""
    if include_raw and raw and rec.get("output_json") is not None:
        preview = raw.strip()
        if len(preview) > _RAW_PREVIEW:
            preview = preview[:_RAW_PREVIEW] + "…"
        if preview and preview != _pretty(rec["output_json"]):
            lines.extend(["-" * 72, "原始输出（截断）", preview])
    lines.append("=" * 72)
    return "\n".join(str(item) for item in lines) + "\n"


def format_llm_console_line(event: dict) -> str:
    rec = enrich_event(event)
    parsed = rec.get("output_json") if isinstance(rec.get("output_json"), dict) else {}
    intent = parsed.get("intent") or ""
    keywords = parsed.get("keywords")
    extras = []
    if intent:
        extras.append(f"intent={intent}")
    if isinstance(keywords, list) and keywords:
        extras.append("keywords=" + ",".join(str(item) for item in keywords[:6]))
    if rec.get("elapsed") is not None:
        extras.append(f"{rec['elapsed']}s")
    user = rec.get("user") or ""
    if len(user) > 40:
        user = user[:40] + "…"
    flag = "OK" if rec.get("ok") else "FAIL"
    extra = ("  " + "  ".join(extras)) if extras else ""
    return (
        f"[LLM] {rec.get('ts') or '-'}  {flag}  {rec.get('stage') or '调用'}  "
        f"用户={user or '（空）'}{extra}"
    )


def _compact_jsonl_record(event: dict) -> dict:
    rec = enrich_event(event)
    output = rec.get("output")
    if isinstance(output, str) and len(output) > _RAW_PREVIEW:
        output = output[:_RAW_PREVIEW] + "…"
    record = {
        "ts": rec.get("ts"),
        "ok": rec.get("ok"),
        "stage": rec.get("stage"),
        "model": rec.get("model"),
        "url": rec.get("url"),
        "attempt": rec.get("attempt"),
        "attempts": rec.get("attempts"),
        "status": rec.get("status"),
        "user": rec.get("user"),
        "system_preview": rec.get("system_preview"),
        "system_chars": rec.get("system_chars"),
        "output_json": rec.get("output_json"),
        "output": output,
        "usage": rec.get("usage"),
    }
    if not rec.get("ok"):
        record["reason"] = rec.get("reason")
        record["error"] = rec.get("error")
    return {key: value for key, value in record.items() if value is not None}


def write_llm_log(event: dict) -> None:
    global _last_prune_day
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    record = {"ts": now.strftime("%Y-%m-%d %H:%M:%S")}
    record.update(event or {})
    day = now.strftime("%Y-%m-%d")
    jsonl_path = LOG_DIR / f"llm-{day}.jsonl"
    text_path = LOG_DIR / f"llm-{day}.log"
    jsonl_line = json.dumps(_compact_jsonl_record(record), ensure_ascii=False, default=str)
    text_block = format_llm_log_text(record, include_raw=True)
    with _lock:
        _append_rotating(jsonl_path, jsonl_line + "\n")
        _append_rotating(text_path, text_block + "\n")
        if _last_prune_day != day:
            _prune_old_logs(now - timedelta(days=_LOG_RETENTION_DAYS))
            _last_prune_day = day
    print(format_llm_console_line(record), flush=True)


def _append_rotating(path: Path, text: str) -> None:
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            incoming_size = len(text.encode("utf-8"))
            if path.exists() and path.stat().st_size + incoming_size > _MAX_LOG_BYTES:
                oldest = path.with_name(path.name + f".{_LOG_BACKUPS}")
                if oldest.exists():
                    oldest.unlink()
                for index in range(_LOG_BACKUPS - 1, 0, -1):
                    source = path.with_name(path.name + f".{index}")
                    if source.exists():
                        os.replace(source, path.with_name(path.name + f".{index + 1}"))
                if path.exists():
                    os.replace(path, path.with_name(path.name + ".1"))
            with path.open("a", encoding="utf-8") as log_file:
                log_file.write(text)
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _prune_old_logs(cutoff: datetime) -> None:
    cutoff_timestamp = cutoff.timestamp()
    for path in LOG_DIR.glob("llm-*"):
        if path.name.endswith(".lock"):
            continue
        try:
            if path.stat().st_mtime < cutoff_timestamp:
                path.unlink()
        except OSError:
            _logger.warning("Unable to prune old LLM log file %s", path.name)


def _write_worker() -> None:
    while True:
        event = _log_queue.get()
        try:
            write_llm_log(event)
        except Exception:
            _logger.exception("Unable to persist queued LLM log")
        finally:
            _log_queue.task_done()


def enqueue_llm_log(event: dict) -> None:
    global _worker_started
    if not _worker_started:
        with _worker_lock:
            if not _worker_started:
                Thread(target=_write_worker, name="llm-log-writer", daemon=True).start()
                _worker_started = True
    try:
        _log_queue.put_nowait(dict(event or {}))
    except queue.Full:
        _logger.warning("LLM log queue full; dropping one diagnostic event")


def rebuild_readable_log(jsonl_path: Path, text_path: Path | None = None) -> int:
    """把已有 jsonl 转成可读 .log，方便回看今天已经落盘的记录。"""
    jsonl_path = Path(jsonl_path)
    if text_path is None:
        text_path = jsonl_path.with_suffix(".log")
    if not jsonl_path.exists():
        return 0
    blocks = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        blocks.append(format_llm_log_text(event))
    text_path.write_text("\n".join(blocks), encoding="utf-8")
    return len(blocks)
