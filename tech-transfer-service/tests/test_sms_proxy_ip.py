from types import SimpleNamespace

from core.rate_limit import _client_ip


def request(peer, xff=""):
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers={"x-forwarded-for": xff})


def test_untrusted_peer_cannot_spoof_ip():
    assert _client_ip(request("8.8.8.8", "1.1.1.1")) == "8.8.8.8"


def test_walk_only_explicitly_trusted_proxy_chain(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,10.0.0.0/24")
    assert _client_ip(request("127.0.0.1", "9.9.9.9, 8.8.8.8, 10.0.0.2")) == "8.8.8.8"


def test_ipv6_normalization_and_invalid_xff(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "::1")
    assert _client_ip(request("::1", "2001:0db8:0:0::1")) == "2001:db8::1"
    assert _client_ip(request("::1", "forged-value")) == "::1"
