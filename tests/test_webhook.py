import hashlib
import hmac
import json
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from bot.app import create_app


def envelope(settings, **overrides):
    message = {
        "from": str(secrets.randbelow(10**11) + 10**11),
        "id": secrets.token_hex(16),
        "timestamp": str(int(time.time())),
        "type": "text",
        "text": {"body": "¿Tienen cortes disponibles?"},
    }
    message.update(overrides)
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": settings.phone_id},
                            "messages": [message],
                        },
                    }
                ]
            }
        ],
    }


def signed(client, settings, payload):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(settings.app_secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhook", content=body, headers={"x-hub-signature-256": signature})


def test_verification_requires_token(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        query = {
            "hub.mode": "subscribe",
            "hub.verify_token": settings.verify_token,
            "hub.challenge": "42",
        }
        assert client.get("/webhook", params=query).text == "42"
        query["hub.verify_token"] = secrets.token_hex(16)
        assert client.get("/webhook", params=query).status_code == 403
        assert client.get("/healthz").json() == {"status": "ok"}


def test_invalid_signature_never_queues(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        assert client.post("/webhook", json=envelope(settings)).status_code == 403
        assert client.app.state.store.counts() == {}


def test_signed_event_is_deduplicated(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        payload = envelope(settings)
        assert signed(client, settings, payload).status_code == 200
        assert signed(client, settings, payload).status_code == 200
        assert client.app.state.store.counts() == {"pending": 1}


def test_tampered_body_fails(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        body = json.dumps(envelope(settings)).encode()
        sig = "sha256=" + hmac.new(settings.app_secret.encode(), body, hashlib.sha256).hexdigest()
        assert (
            client.post(
                "/webhook", content=body + b" ", headers={"x-hub-signature-256": sig}
            ).status_code
            == 403
        )


def test_other_phone_and_statuses_are_ignored(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        payload = envelope(settings)
        value = payload["entry"][0]["changes"][0]["value"]
        value["metadata"]["phone_number_id"] = "0"
        assert signed(client, settings, payload).status_code == 200
        value["metadata"]["phone_number_id"] = settings.phone_id
        value.pop("messages")
        value["statuses"] = []
        assert signed(client, settings, payload).status_code == 200
        assert client.app.state.store.counts() == {}


@pytest.mark.parametrize("payload", [[], {"object": "whatsapp_business_account", "entry": [None]}])
def test_malformed_signed_payload(settings, payload):
    with TestClient(create_app(settings, start_worker=False)) as client:
        assert signed(client, settings, payload).status_code == 400


def test_size_limit(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        assert client.post("/webhook", content=b"x" * 65537).status_code == 413


def test_old_event_cannot_replay_after_retention(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        payload = envelope(settings, timestamp=str(int(time.time()) - 86400))
        assert signed(client, settings, payload).status_code == 200
        assert client.app.state.store.counts() == {}


def test_rate_limit(settings):
    settings.rate_limit = 2
    with TestClient(create_app(settings, start_worker=False)) as client:
        sender = str(secrets.randbelow(10**11) + 10**11)
        for _ in range(3):
            assert (
                signed(client, settings, envelope(settings, **{"from": sender})).status_code == 200
            )
        assert client.app.state.store.counts() == {"pending": 2}


def test_nontext_uses_fixed_reply(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        signed(client, settings, envelope(settings, type="image", text=None))
        assert "mensajes de texto" in client.app.state.store.next_job()["response"]
