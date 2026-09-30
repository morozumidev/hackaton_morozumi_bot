import secrets

import pytest
from dotenv import set_key

from bot.config import ROOT, Settings
from bot.storage import Store


@pytest.fixture
def settings(tmp_path):
    path = tmp_path / ".env"
    path.write_text((ROOT / ".env.example").read_text())
    for name in (
        "WHATSAPP_ACCESS_TOKEN",
        "META_APP_SECRET",
        "WEBHOOK_VERIFY_TOKEN",
        "SESSION_SECRET",
    ):
        set_key(path, name, secrets.token_urlsafe(48))
    set_key(path, "WHATSAPP_PHONE_NUMBER_ID", str(secrets.randbelow(10**14) + 10**14))
    set_key(path, "DATABASE_PATH", str(tmp_path / "data" / "bot.sqlite3"))
    return Settings.load(path)


@pytest.fixture
def store(settings):
    return Store(settings.database, settings.timezone, settings.slot_hours, settings.memory_ttl)
