import pytest
from fastapi import HTTPException
from starlette.requests import Request

from modules.security.sms_request import validate_sms_request


def req(body=b"{}", headers=None, scheme="https"):
    hs = [(b"content-type", b"application/json")]
    hs += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/sms",
            "headers": hs,
            "scheme": scheme,
            "client": ("8.8.8.8", 123),
            "server": ("x", 443),
            "query_string": b"",
        },
        receive,
    )


@pytest.mark.asyncio
async def test_valid_public_context():
    context = await validate_sms_request(req())
    assert context.source == "h5" and context.ip == "8.8.8.8" and context.request_id


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"[]", b"x" * 4097])
async def test_rejects_invalid_or_oversized_body(body):
    with pytest.raises(HTTPException):
        await validate_sms_request(req(body))


@pytest.mark.asyncio
async def test_rejects_bad_device_id():
    with pytest.raises(HTTPException):
        await validate_sms_request(req(headers={"x-device-id": "bad id"}))


@pytest.mark.asyncio
async def test_service_signature_replay_and_body_tamper(monkeypatch):
    import hashlib
    import hmac
    import time

    import modules.security.sms_request as m
    from config import settings

    secret = "service-secret-independent-of-sms-key"
    monkeypatch.setattr(settings, "SMS_SERVICE_CLIENTS", {"backend": secret})
    used = set()

    async def store(n, ttl=300):
        if n in used:
            return False
        used.add(n)
        return True

    monkeypatch.setattr(m, "_nonce_store", store)
    timestamp = str(int(time.time()))
    nonce = "a" * 24
    canonical = "\n".join(("POST", "/sms", hashlib.sha256(b"{}").hexdigest(), timestamp, nonce, "backend"))
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    hs = {
        "x-client-source": "service",
        "x-sms-client-id": "backend",
        "x-sms-timestamp": timestamp,
        "x-sms-nonce": nonce,
        "x-sms-signature": sig,
    }
    assert (await validate_sms_request(req(headers=hs))).source == "service"
    with pytest.raises(HTTPException) as e:
        await validate_sms_request(req(headers=hs))
    assert e.value.status_code == 409
    for body, headers in [
        (b'{"tampered":true}', hs),
        (b"{}", {**hs, "x-sms-timestamp": "1"}),
        (b"{}", {**hs, "x-sms-signature": "0" * 64}),
    ]:
        with pytest.raises(HTTPException) as e:
            await validate_sms_request(req(body, headers))
        assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_origin_cannot_bypass_by_claiming_mini():
    with pytest.raises(HTTPException) as e:
        await validate_sms_request(req(headers={"origin": "https://evil.example", "x-client-source": "mini"}))
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_public_http_and_fake_forwarded_https_rejected():
    with pytest.raises(HTTPException):
        await validate_sms_request(
            req(scheme="http", headers={"x-forwarded-proto": "https", "x-forwarded-for": "1.2.3.4"})
        )


@pytest.mark.asyncio
async def test_real_redis_parallel_nonce(monkeypatch):
    import asyncio
    import os
    import uuid

    import modules.security.sms_request as m

    url = os.getenv("SMS_TEST_REDIS_URL")
    if not url:
        pytest.skip("set SMS_TEST_REDIS_URL")
    monkeypatch.setattr(m.settings, "REDIS_URL", url)
    nonce = uuid.uuid4().hex
    results = await asyncio.gather(*(m._nonce_store(nonce) for i in range(20)))
    assert sum(results) == 1
