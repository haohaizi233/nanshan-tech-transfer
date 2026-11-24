from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from config import settings
from core.rate_limit import _client_ip, _is_trusted_proxy
from core.response import get_request_id


@dataclass(frozen=True)
class SmsRequestContext:
    ip: str
    device_id: str | None
    source: str
    request_id: str


class DeviceRiskAdapter:
    """Replace on the server for platform-verified attestation, never client MACs.

    Default device IDs are resettable, untrusted behavioral signals. Returning
    an ID never confers user identity or exempts any hard quota.
    """

    def identify(self, device):
        if device is not None and (
            not isinstance(device, str) or len(device) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", device)
        ):
            raise HTTPException(400, "Invalid device ID")
        return device


device_risk_adapter = DeviceRiskAdapter()


async def _body(request: Request) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > settings.SMS_REQUEST_MAX_BYTES:
            raise HTTPException(413, "Request body too large")
    return bytes(data)


def _clients() -> dict[str, str]:
    value: Any = getattr(settings, "SMS_SERVICE_CLIENTS", {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


async def _nonce_store(nonce: str, ttl: int = 300) -> bool:
    import redis.asyncio as redis_async

    client = redis_async.Redis.from_url(
        getattr(settings, "REDIS_URL", ""), protocol=2, socket_connect_timeout=2, socket_timeout=2
    )
    try:
        return bool(await client.set(f"sms:req:nonce:{nonce}", "1", nx=True, ex=ttl))
    finally:
        await client.aclose()


async def validate_sms_request(request: Request) -> SmsRequestContext:
    headers = request.headers
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(415, "Content-Type must be application/json")
    raw = await _body(request)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "JSON object required")

    source = headers.get("x-client-source", "h5").strip().lower()
    if source not in {"h5", "mini", "user", "service"}:
        raise HTTPException(400, "Invalid request source")
    if settings.is_production_like or source in {"h5", "mini"}:
        scheme = request.url.scheme
        forwarded_proto = headers.get("x-forwarded-proto", "").split(",")[-1].strip().lower()
        trusted = request.client and _is_trusted_proxy(request.client.host)
        if scheme != "https" and not (forwarded_proto == "https" and trusted):
            raise HTTPException(400, "HTTPS required")
    # A source header is not authentication and cannot bypass the browser gate.
    origin = headers.get("origin")
    allowed = getattr(settings, "CORS_ORIGINS", []) or []
    if origin and origin not in allowed and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origin not allowed")
    if source == "user" and not headers.get("authorization", "").startswith("Bearer "):
        raise HTTPException(401, "Bearer authentication required")

    if source == "service":
        client_id = headers.get("x-sms-client-id", "")
        timestamp, nonce, signature = (
            headers.get(k, "") for k in ("x-sms-timestamp", "x-sms-nonce", "x-sms-signature")
        )
        secret = _clients().get(client_id)
        if (
            not client_id
            or not isinstance(secret, str)
            or not secret
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce)
        ):
            raise HTTPException(401, "Invalid service signature")
        try:
            ts = int(timestamp)
        except ValueError:
            raise HTTPException(401, "Invalid service signature") from None
        if abs(time.time() - ts) > settings.SMS_SERVICE_TIMESTAMP_WINDOW_SECONDS:
            raise HTTPException(401, "Expired service signature")
        if request.url.query or "%" in request.scope.get("raw_path", b"").decode("ascii", errors="ignore"):
            raise HTTPException(400, "Canonical path required without query")
        canonical = "\n".join(
            (request.method.upper(), request.url.path, hashlib.sha256(raw).hexdigest(), timestamp, nonce, client_id)
        )
        expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            raise HTTPException(401, "Invalid service signature")
        try:
            nonce_digest = hmac.new(secret.encode(), (client_id + ":" + nonce).encode(), hashlib.sha256).hexdigest()
            # Cover the entire +/- clock-skew interval, including future-dated
            # requests whose signatures remain valid after a simple 300s TTL.
            if not await _nonce_store(nonce_digest, 2 * settings.SMS_SERVICE_TIMESTAMP_WINDOW_SECONDS + 1):
                raise HTTPException(409, "Replay detected")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Security service unavailable") from None

    device = headers.get("x-device-id") or payload.get("deviceId")
    device = device_risk_adapter.identify(device)
    return SmsRequestContext(_client_ip(request), device, source, get_request_id())


class SmsBodyLimitMiddleware:
    """Bound actual bytes before FastAPI eagerly buffers/parses JSON."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        paths = (
            "/auth/recovery/start",
            "/auth/recovery/verify",
            "/auth/recovery/complete",
            "/me/security/contact/challenge",
            "/me/security/contact/verify",
            "/me/security/step-up/challenge",
        )
        if scope["type"] != "http" or not any(scope.get("path", "").endswith(p) for p in paths):
            return await self.app(scope, receive, send)
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > settings.SMS_REQUEST_MAX_BYTES:
                from starlette.responses import JSONResponse

                return await JSONResponse({"detail": "Request body too large"}, 413)(scope, receive, send)
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

        async def bounded_receive():
            nonlocal chunks
            if chunks is not None:
                body = b"".join(chunks)
                chunks = None
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, bounded_receive, send)
