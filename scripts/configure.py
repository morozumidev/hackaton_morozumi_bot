import argparse
import getpass
import os
import secrets

from dotenv import dotenv_values, set_key

from bot.config import ROOT

PROMPTS = {
    "WHATSAPP_ACCESS_TOKEN": "Access token de WhatsApp",
    "WHATSAPP_PHONE_NUMBER_ID": "Phone Number ID de Meta (no es el número de teléfono)",
    "META_APP_SECRET": "App Secret de Meta",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    path = ROOT / ".env"
    if not path.exists():
        with path.open("x") as file:
            file.write((ROOT / ".env.example").read_text())
    os.chmod(path, 0o600)
    values = dotenv_values(path, interpolate=False)
    for key in ("WEBHOOK_VERIFY_TOKEN", "SESSION_SECRET"):
        if not values.get(key):
            set_key(path, key, secrets.token_urlsafe(48))
    if not args.init_only:
        for key, prompt in PROMPTS.items():
            suffix = " [Enter conserva el valor actual]" if values.get(key) else ""
            value = getpass.getpass(prompt + suffix + ": ").strip()
            if value:
                set_key(path, key, value)
    os.chmod(path, 0o600)
    print("Configuración guardada en .env con permisos 600. No se mostraron los valores.")


if __name__ == "__main__":
    main()
