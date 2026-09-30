import asyncio
import os
import secrets

import httpx

from bot.agent import Agent
from bot.config import ROOT, ConfigError, Settings
from bot.providers import ChatAPI, Guards
from bot.security import owner_id
from bot.storage import Store


async def main():
    os.umask(0o077)
    try:
        settings = Settings.load(whatsapp=False)
    except ConfigError as error:
        raise SystemExit(str(error)) from None
    store = Store(
        ROOT / "data/chat.sqlite3", settings.timezone, settings.slot_hours, settings.memory_ttl
    )
    owner = owner_id("local-chat", settings.session_secret)
    async with httpx.AsyncClient(timeout=settings.timeout, trust_env=False) as client:
        agent = Agent(
            store,
            ChatAPI(client, settings.llm_url, settings.llm_model, settings.llm_key),
            Guards(client, settings),
        )
        print("Barbería Morozumi · chat local con Llama · escribe SALIR para terminar")
        while True:
            try:
                text = input("Tú: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.upper() == "SALIR":
                break
            print("Bot:", await agent.reply(owner, secrets.token_hex(16), text))


if __name__ == "__main__":
    asyncio.run(main())
