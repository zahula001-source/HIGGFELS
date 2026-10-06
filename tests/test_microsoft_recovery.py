import io
import json

from app.services import microsoft_recovery as recovery


def test_parse_v1_account():
    account = recovery.parse_microsoft_account("main@example.com|secret|refresh|client")
    assert account is not None
    assert account.email == "main@example.com"
    assert account.client_id == "client"
    assert not account.is_v2


def test_parse_v2_account():
    account = recovery.parse_microsoft_account(
        "main@example.com|secret|refresh|client|backup@wmhotmail.com|123456"
    )
    assert account is not None
    assert account.is_v2
    assert account.recovery_email == "backup@wmhotmail.com"
    assert account.recovery_password == "123456"


def test_roundcube_api_disables_proxy_and_extracts_code(monkeypatch):
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class Opener:
        def open(self, request, timeout):
            captured["payload"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            body = {"data": [{"messages": [{"uid": "44", "code": "892073"}]}]}
            return Response(json.dumps(body).encode())

    def fake_build_opener(handler):
        captured["proxies"] = handler.proxies
        return Opener()

    monkeypatch.setattr(recovery.urllib.request, "build_opener", fake_build_opener)
    uids, code = recovery.fetch_roundcube_messages("box@wmhotmail.com", "pw")
    assert captured["proxies"] == {}
    assert captured["payload"] == {
        "mode": "roundcube",
        "data": "box@wmhotmail.com|pw",
    }
    assert uids == {"44"}
    assert code == "892073"
