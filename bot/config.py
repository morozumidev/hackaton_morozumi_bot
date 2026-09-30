import re
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


class ConfigError(Exception):
    pass


def validate_url(url: str, name: str) -> str:
    parts = urlsplit(url)
    local = parts.hostname in {"127.0.0.1", "localhost", "::1"}
    if (parts.scheme != "https" and not (parts.scheme == "http" and local)) or (
        not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
    ):
        raise ConfigError(
            f"{name}: usa HTTPS, o HTTP solamente en localhost; sin credenciales en URL."
        )
    return url.rstrip("/")


@dataclass(repr=False)
class Settings:
    access_token: str = field(repr=False)
    phone_id: str = field(repr=False)
    app_secret: str = field(repr=False)
    verify_token: str = field(repr=False)
    session_secret: str = field(repr=False)
    graph_version: str
    llm_url: str
    llm_model: str
    llm_key: str = field(repr=False)
    guard_url: str
    guard_model: str
    guard_key: str = field(repr=False)
    prompt_guard_key: str = field(repr=False)
    prompt_guard_model: str
    host: str
    port: int
    timezone: str
    database: Path
    slot_hours: tuple[str, ...]
    timeout: int
    memory_ttl: int
    rate_limit: int

    @classmethod
    def load(cls, path: Path = ROOT / ".env", *, whatsapp: bool = True):
        values = dotenv_values(path, interpolate=False)

        def get(name: str) -> str:
            return (values.get(name) or "").strip()

        required = [
            "SESSION_SECRET",
            "LLM_BASE_URL",
            "LLM_MODEL",
            "GUARD_BASE_URL",
            "GUARD_MODEL",
            "GRAPH_API_VERSION",
            "HOST",
            "PORT",
            "TIMEZONE",
            "DATABASE_PATH",
            "SLOT_HOURS",
            "HTTP_TIMEOUT_SECONDS",
            "MEMORY_TTL_HOURS",
            "RATE_LIMIT_PER_MINUTE",
        ]
        if whatsapp:
            required += [
                "WHATSAPP_ACCESS_TOKEN",
                "WHATSAPP_PHONE_NUMBER_ID",
                "META_APP_SECRET",
                "WEBHOOK_VERIFY_TOKEN",
            ]
        missing = [name for name in required if not get(name)]
        if missing:
            raise ConfigError("Faltan variables en .env: " + ", ".join(missing))
        if len(get("SESSION_SECRET")) < 32:
            raise ConfigError("SESSION_SECRET necesita al menos 32 caracteres aleatorios.")
        if whatsapp and len(get("WEBHOOK_VERIFY_TOKEN")) < 32:
            raise ConfigError("WEBHOOK_VERIFY_TOKEN necesita al menos 32 caracteres aleatorios.")
        if whatsapp and not re.fullmatch(r"[0-9]{5,30}", get("WHATSAPP_PHONE_NUMBER_ID")):
            raise ConfigError("WHATSAPP_PHONE_NUMBER_ID debe ser el ID numérico de Meta.")
        if not re.fullmatch(r"v[0-9]{2}\.0", get("GRAPH_API_VERSION")):
            raise ConfigError("GRAPH_API_VERSION no tiene un formato válido.")
        try:
            ZoneInfo(get("TIMEZONE"))
            hours = tuple(get("SLOT_HOURS").split(","))
            for hour in hours:
                if not re.fullmatch(r"\d{2}:\d{2}", hour):
                    raise ValueError
                time.fromisoformat(hour)
            minutes = sorted(int(h[:2]) * 60 + int(h[3:]) for h in hours)
            if any(b - a < 30 for a, b in zip(minutes, minutes[1:])):
                raise ValueError
            port = int(get("PORT"))
            timeout = int(get("HTTP_TIMEOUT_SECONDS"))
            ttl = int(get("MEMORY_TTL_HOURS"))
            rate = int(get("RATE_LIMIT_PER_MINUTE"))
            if not (
                1 <= port <= 65535
                and 5 <= timeout <= 180
                and 1 <= ttl <= 168
                and 1 <= rate <= 60
                and 1 <= len(hours) <= 12
            ):
                raise ValueError
        except (ValueError, KeyError):
            raise ConfigError(
                "Revisa zona horaria, horarios, puerto y límites numéricos en .env."
            ) from None
        if get("PROMPT_GUARD_API_KEY") and not get("PROMPT_GUARD_MODEL"):
            raise ConfigError("Falta PROMPT_GUARD_MODEL.")
        return cls(
            get("WHATSAPP_ACCESS_TOKEN"),
            get("WHATSAPP_PHONE_NUMBER_ID"),
            get("META_APP_SECRET"),
            get("WEBHOOK_VERIFY_TOKEN"),
            get("SESSION_SECRET"),
            get("GRAPH_API_VERSION"),
            validate_url(get("LLM_BASE_URL"), "LLM_BASE_URL"),
            get("LLM_MODEL"),
            get("LLM_API_KEY"),
            validate_url(get("GUARD_BASE_URL"), "GUARD_BASE_URL"),
            get("GUARD_MODEL"),
            get("GUARD_API_KEY"),
            get("PROMPT_GUARD_API_KEY"),
            get("PROMPT_GUARD_MODEL"),
            get("HOST"),
            port,
            get("TIMEZONE"),
            ROOT / get("DATABASE_PATH"),
            hours,
            timeout,
            ttl,
            rate,
        )
