import argparse
import asyncio

import httpx

from bot.config import ConfigError, Settings
from bot.providers import ChatAPI, Guards, RemoteError
from bot.storage import Store


async def check_models(settings):
    async with httpx.AsyncClient(timeout=settings.timeout, trust_env=False) as client:
        try:
            guards = Guards(client, settings)
            safe = await guards.content_safe(
                [{"role": "user", "content": "Hola, quiero un corte de cabello."}]
            )
            if not safe:
                raise RemoteError()
            if not await guards.injection_safe("Quiero consultar horarios de la barbería."):
                raise RemoteError()
            model = ChatAPI(client, settings.llm_url, settings.llm_model, settings.llm_key)
            result = await model.complete(
                [{"role": "user", "content": "Responde únicamente: listo"}]
            )
            if not result.get("content"):
                raise RemoteError()
        except RemoteError:
            raise SystemExit(
                "Falló la conexión o clasificación. Revisa modelos, URLs y claves en .env."
            ) from None
    print("Llama y Llama Guard respondieron correctamente.")
    print("Prompt Guard: " + ("conectado" if settings.prompt_guard_key else "no configurado"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings.load(whatsapp=not args.models)
    except ConfigError as error:
        raise SystemExit(str(error)) from None
    if args.models:
        asyncio.run(check_models(settings))
    else:
        print("Configuración de WhatsApp completa. No se enviaron mensajes.")
        print("Llama Guard: configurado.")
        print("Prompt Guard: " + ("configurado" if settings.prompt_guard_key else "no configurado"))
        if settings.database.exists():
            store = Store(
                settings.database, settings.timezone, settings.slot_hours, settings.memory_ttl
            )
            print("Entregas locales:", store.counts())


if __name__ == "__main__":
    main()
