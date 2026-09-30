import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from bot.config import ROOT

SECRET_NAMES = {
    "WHATSAPP_ACCESS_TOKEN",
    "META_APP_SECRET",
    "WEBHOOK_VERIFY_TOKEN",
    "SESSION_SECRET",
    "LLM_API_KEY",
    "GUARD_API_KEY",
    "PROMPT_GUARD_API_KEY",
    "NGROK_AUTHTOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
}
PATTERNS = [
    re.compile(r"\b(?:gsk_|ghp_|github_pat_|sk-)[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bEAA[A-Za-z0-9]{50,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def forbidden(path: str):
    p = Path(path)
    return (
        "data" in p.parts
        or p.name == ".env"
        or (p.name.startswith(".env.") and p.name != ".env.example")
        or p.suffix in {".pem", ".key", ".db", ".sqlite", ".sqlite3", ".ipynb", ".log"}
    )


def main():
    private = dotenv_values(ROOT / ".env", interpolate=False)
    secrets = [private[k] for k in SECRET_NAMES if private.get(k) and len(private[k]) >= 8]
    paths = set(
        git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    ) - {""}
    indexed = set(git("ls-files", "--cached", "-z").decode().split("\0")) - {""}
    problems = set()
    for path in paths:
        if forbidden(path):
            problems.add(path)
            continue
        versions = []
        file = ROOT / path
        if file.is_file():
            versions.append(file.read_bytes())
        if path in indexed:
            versions.append(git("show", ":" + path))
        for raw in versions:
            text = raw.decode("utf-8", errors="replace")
            if any(secret in text for secret in secrets) or any(
                pattern.search(text) for pattern in PATTERNS
            ):
                problems.add(path)
    example = dotenv_values(ROOT / ".env.example", interpolate=False)
    if any(example.get(name) for name in SECRET_NAMES):
        problems.add(".env.example")
    if problems:
        print("Revisión detenida. Archivos que necesitan inspección local:")
        for path in sorted(problems):
            print(path)
        raise SystemExit(1)
    print(
        f"Revisión completada: {len(paths)} archivos; sin coincidencias de secretos ni archivos privados."
    )


if __name__ == "__main__":
    main()
