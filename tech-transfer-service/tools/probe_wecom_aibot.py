"""企业微信智能机器人长连接连通性探测（独立脚本，不加载 FastAPI）。

验证 Bot ID + Secret 能否完成 aibot_subscribe。成功后立刻断开，
避免长期占用「同一 Bot 只能一条长连接」的槽位。

不 import app / db，不会重启或改写正在跑的 8787 后端。

用法：
  凭证写在 tech-transfer-service/.env（WECOM_BOT_ID / WECOM_SECRET），或由环境变量覆盖：
    python tools/probe_wecom_aibot.py

可选：
  python tools/probe_wecom_aibot.py --tls-only
      只测 TLS，不订阅（不会踢掉已在线的爱马仕 gateway）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import ssl
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

WS_URL = os.environ.get("WECOM_WEBSOCKET_URL", "wss://openws.work.weixin.qq.com")
HERMES_API_HOST = os.environ.get("HERMES_API_HOST", "127.0.0.1")
HERMES_API_PORT = int(os.environ.get("HERMES_API_PORT", "8642"))
SUBSCRIBE_TIMEOUT = 20
PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        extra = f" — {detail}" if detail else ""
        print(f"  [FAIL] {name}{extra}")


def mask_id(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return value[:2] + "…"
    return value[:4] + "…" + value[-4:]


def load_env_file() -> None:
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_credentials() -> tuple[str, str]:
    load_env_file()
    bot_id = (os.environ.get("WECOM_BOT_ID") or "").strip()
    secret = (os.environ.get("WECOM_SECRET") or os.environ.get("WECOM_BOT_SECRET") or "").strip()
    return bot_id, secret


def tcp_connect(host: str, port: int, timeout: float = 8.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as exc:
        return False, str(exc)


def tls_handshake(host: str, port: int = 443, timeout: float = 10.0) -> tuple[bool, str]:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                return True, tls.version() or "TLS"
    except OSError as exc:
        return False, str(exc)


def parse_subscribe_result(raw: str) -> tuple[bool, str, dict]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False, f"non-json response: {raw[:200]}", {}
    if not isinstance(payload, dict):
        return False, f"response is not an object: {raw[:200]}", {}
    errcode = payload.get("errcode")
    if errcode is None and isinstance(payload.get("body"), dict):
        errcode = payload["body"].get("errcode")
    errmsg = payload.get("errmsg") or ""
    if isinstance(payload.get("body"), dict) and not errmsg:
        errmsg = payload["body"].get("errmsg") or ""
    ok = errcode == 0
    detail = f"errcode={errcode} errmsg={errmsg or '(none)'}"
    if errcode == 853000:
        detail += (
            " | copy Bot ID/Secret again from WeCom (do not OCR); "
            "i/l/1 mix-ups and a rotated Secret both trigger 853000"
        )
    return ok, detail, payload


async def subscribe_once(bot_id: str, secret: str) -> tuple[bool, str]:
    try:
        import websockets
    except ImportError:
        return False, "当前 Python 没有 websockets（uvicorn[standard] 一般已带；可 pip install websockets）"

    req_id = uuid.uuid4().hex
    frame = {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": req_id},
        "body": {"bot_id": bot_id, "secret": secret},
    }
    connect_kwargs = {
        "open_timeout": SUBSCRIBE_TIMEOUT,
        "close_timeout": 5,
        "ping_interval": None,
        "max_size": 2**20,
    }
    last_error = None
    for extra in ({"proxy": None}, {}):
        kwargs = dict(connect_kwargs)
        kwargs.update(extra)
        try:
            async with websockets.connect(
                os.environ.get("WECOM_WEBSOCKET_URL", "wss://openws.work.weixin.qq.com"),
                **kwargs,
            ) as ws:
                await ws.send(json.dumps(frame, ensure_ascii=False))
                raw = await asyncio.wait_for(ws.recv(), timeout=SUBSCRIBE_TIMEOUT)
            ok, detail, _payload = parse_subscribe_result(raw)
            if ok:
                return True, detail
            return False, detail
        except TypeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
    return False, f"{type(last_error).__name__}: {last_error}"


def _use_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def main() -> int:
    _use_utf8_stdio()
    parser = argparse.ArgumentParser(description="Probe WeCom AI Bot long-connection without touching FastAPI")
    parser.add_argument(
        "--tls-only",
        action="store_true",
        help="只测 TLS，不发送 aibot_subscribe（不会踢掉已在线的爱马仕 gateway）",
    )
    args = parser.parse_args()

    bot_id, secret = load_credentials()
    ws_url = os.environ.get("WECOM_WEBSOCKET_URL", "wss://openws.work.weixin.qq.com")
    parsed = urlparse(ws_url)
    host = parsed.hostname or "openws.work.weixin.qq.com"
    port = parsed.port or 443

    print("WeCom AI Bot connectivity probe")
    print(f"  ws = {ws_url}")
    print(f"  bot_id = {mask_id(bot_id)}")
    print("  secret = (read from env, not printed)")
    print("  does not load FastAPI / does not bind 8787")
    print()

    print("[1] credentials")
    check("WECOM_BOT_ID is set", bool(bot_id))
    check("WECOM_SECRET is set", bool(secret))

    print("\n[2] WeCom gateway network")
    ok, detail = tcp_connect(host, port)
    check(f"TCP {host}:{port}", ok, detail)
    ok, detail = tls_handshake(host, port)
    check(f"TLS handshake {host}", ok, detail)

    print("\n[3] aibot_subscribe")
    if args.tls_only:
        print("  [SKIP] --tls-only: no subscribe, will not displace a live Hermes gateway")
    elif not bot_id or not secret:
        check("subscribe AI bot", False, "missing Bot ID or Secret")
    else:
        print("  note: one bot can keep only one live connection; a successful subscribe briefly displaces an existing gateway, then this script disconnects.")
        started = time.time()
        ok, detail = asyncio.run(subscribe_once(bot_id, secret))
        elapsed = time.time() - started
        check(f"WebSocket subscribe ({elapsed:.1f}s)", ok, detail)

    print("\n[4] Hermes OpenAI-compatible HTTP (informational)")
    hosts = []
    provider_base = (os.environ.get("AI_PROVIDER_BASE") or "").strip()
    if provider_base:
        parsed_base = urlparse(provider_base if "://" in provider_base else f"http://{provider_base}")
        if parsed_base.hostname:
            hosts.append((parsed_base.hostname, parsed_base.port or 8642, "AI_PROVIDER_BASE"))
    hosts.extend(
        [
            (HERMES_API_HOST, HERMES_API_PORT, "HERMES_API_HOST"),
            ("192.168.2.79", 8642, "lan-db-host"),
            ("43.138.138.200", 8642, "patent-host"),
        ]
    )
    seen = set()
    found = False
    for host, port, label in hosts:
        key = (host, port)
        if key in seen:
            continue
        seen.add(key)
        ok, detail = tcp_connect(host, port, timeout=2.0)
        if ok:
            found = True
            print(f"  [INFO] {host}:{port} listening ({label})")
        else:
            print(f"  [INFO] {host}:{port} not listening ({label}) — {detail}")
    if not found:
        print("         remote Hermes HTTP URL is not on this machine; set AI_PROVIDER_BASE later")

    print()
    print(f"=== wecom aibot probe: {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
