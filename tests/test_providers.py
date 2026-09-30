import asyncio
import secrets

import httpx
import pytest

from bot.providers import ChatAPI, Guards, RemoteError, WhatsApp
from bot.security import redact, signature_valid


def run_guard(settings, content, *, injection=False):
    async def run():
        def handler(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            guards = Guards(client, settings)
            if injection:
                return await guards.injection_safe("Quiero una cita")
            return await guards.content_safe([{"role": "user", "content": "Hola"}])

    return asyncio.run(run())


@pytest.mark.parametrize("content, expected", [("safe", True), ("unsafe\nS1", False)])
def test_llama_guard_protocol(settings, content, expected):
    assert run_guard(settings, content) is expected


@pytest.mark.parametrize("content", ["", "safe\nunsafe", None, "No sé"])
def test_invalid_guard_output_fails_closed(settings, content):
    with pytest.raises(RemoteError):
        run_guard(settings, content)


@pytest.mark.parametrize("content, expected", [("0.1", True), ("0.95", False)])
def test_prompt_guard_protocol(settings, content, expected):
    settings.prompt_guard_key = secrets.token_urlsafe(32)
    assert run_guard(settings, content, injection=True) is expected


@pytest.mark.parametrize("content", ["nan", "inf", "2", "safe"])
def test_invalid_prompt_score_fails_closed(settings, content):
    settings.prompt_guard_key = secrets.token_urlsafe(32)
    with pytest.raises(RemoteError):
        run_guard(settings, content, injection=True)


def test_provider_errors_do_not_expose_secrets(settings):
    async def run():
        def handler(request):
            return httpx.Response(401, json={"error": settings.access_token})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(RemoteError) as error:
                await WhatsApp(client, settings).send(secrets.token_hex(16), "Hola")
            assert settings.access_token not in str(error.value)

    asyncio.run(run())


def test_local_model_does_not_receive_auth_header(settings):
    async def run():
        def handler(request):
            assert "Authorization" not in request.headers
            return httpx.Response(200, json={"choices": [{"message": {"content": "Hola"}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await ChatAPI(client, settings.llm_url, settings.llm_model).complete([])

    asyncio.run(run())


def test_redaction_preserves_dates_and_slot_ids():
    text = "Cita 2026-10-01, horario 20261001-1600, precio 150"
    assert redact(text) == text
    phone = str(secrets.randbelow(10**11) + 10**11)
    assert phone not in redact(f"mi número es {phone}")
    assert "correo omitido" in redact("contacto@example.org")


def test_non_ascii_signature_is_rejected():
    assert not signature_valid(b"{}", "sha256=á", secrets.token_hex(16))
