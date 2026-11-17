from urllib.parse import parse_qs

import pytest

from modules.security.provider import ProviderError, SendCloudSmsProvider


class Response:
    def __init__(self, obj):
        self.obj = obj

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self):
        import json

        return json.dumps(self.obj).encode()


def test_send_task_receipt_and_stable_retry(monkeypatch):
    import modules.security.provider as p

    calls = []

    def open_(req, timeout):
        calls.append(req.data.decode())
        if len(calls) == 1:
            raise TimeoutError("private")
        return Response({"result": True, "statusCode": 200, "message": "ok", "info": {"smsIds": ["provider-1"]}})

    monkeypatch.setattr(p.urllib.request, "urlopen", open_)
    provider = SendCloudSmsProvider("u", "secret", 123)
    receipt = provider.send_task("13800138000", "123456", "reset_password", send_request_id="stable-id")
    assert receipt.accepted is True
    assert receipt.request_id == "stable-id"
    assert receipt.provider_ids == ("provider-1",)

    assert parse_qs(calls[0])["sendRequestId"] == ["stable-id"]
    fields = parse_qs(calls[0])
    assert fields["vars"] == ['{"%code%":"123456"}']
    assert calls[0] == calls[1]


def test_business_rejection_not_retried_and_sanitized(monkeypatch, caplog):
    import modules.security.provider as p

    calls = []
    monkeypatch.setattr(
        p.urllib.request,
        "urlopen",
        lambda *a, **k: (
            calls.append(1) or Response({"result": False, "statusCode": 411, "message": "secret 123456 phone"})
        ),
    )
    provider = SendCloudSmsProvider("u", "secret", 123)
    with pytest.raises(ProviderError) as error:
        provider.send_task("13800138000", "123456", "reset_password", send_request_id="stable")
    assert len(calls) == 1
    assert not error.value.outcome_unknown
    assert error.value.reason_code == "invalid_parameters"
    assert error.value.provider_status == 411
    assert error.value.request_attempted is True
    assert "123456" not in str(error.value)


def test_sendcloud_smsids_field(monkeypatch):
    import modules.security.provider as p

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return b'{"result":true,"statusCode":200,"info":{"smsIds":["a","b"]}}'

    monkeypatch.setattr(p.urllib.request, "urlopen", lambda *a, **k: R())
    x = p.SendCloudSmsProvider("u", "k", 123).send_task("13800138000", "123456", "bind_phone", send_request_id="abc")
    assert x.provider_ids == ("a", "b")


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (590, "provider_rejected"),
        (400, "duplicate_request"),
        (311, "partial_acceptance"),
        (432, "template_not_approved"),
        (499, "insufficient_balance"),
    ],
)
def test_provider_status_classification(monkeypatch, status, reason):
    import modules.security.provider as p

    monkeypatch.setattr(p.urllib.request, "urlopen", lambda *a, **k: Response({"result": False, "statusCode": status}))
    with pytest.raises(ProviderError) as error:
        SendCloudSmsProvider("u", "k", 123).send_task("13800138000", "123456", "bind_phone", send_request_id="abc")
    assert error.value.reason_code == reason
    assert error.value.provider_status == status
    assert error.value.request_attempted is True
    assert error.value.outcome_unknown is (status in {311, 400})


def test_accepted_without_sms_ids_is_still_accepted(monkeypatch):
    import modules.security.provider as p

    monkeypatch.setattr(
        p.urllib.request, "urlopen", lambda *a, **k: Response({"result": True, "statusCode": 200, "info": {}})
    )
    receipt = SendCloudSmsProvider("u", "k", 123).send_task(
        "13800138000", "123456", "bind_phone", send_request_id="abc"
    )
    assert receipt.accepted and receipt.provider_ids == () and receipt.request_id == "abc"


def test_invalid_json_is_unknown_and_attempted(monkeypatch):
    import modules.security.provider as p

    class R(Response):
        def read(self):
            return b"not-json"

    monkeypatch.setattr(p.urllib.request, "urlopen", lambda *a, **k: R({}))
    with pytest.raises(ProviderError) as error:
        SendCloudSmsProvider("u", "k", 123).send_task("13800138000", "123456", "bind_phone", send_request_id="abc")
    assert error.value.reason_code == "invalid_response" and error.value.outcome_unknown
    assert error.value.request_attempted
