import hashlib
import hmac
import re
import unicodedata

MAX_TEXT = 1200
BLOCKED = "Puedo ayudarte con los servicios y citas de la barbería, pero no con esa solicitud."
UNAVAILABLE = "No pude completar la consulta. Inténtalo de nuevo en un momento."


def signature_valid(body: bytes, signature: str, secret: str) -> bool:
    if not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, signature)


def owner_id(sender: str, secret: str) -> str:
    return hmac.new(secret.encode(), sender.encode(), hashlib.sha256).hexdigest()


def normalize(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    ).strip()


def suspicious(text: str) -> bool:
    return bool(
        re.search(
            r"(ignora|ignore|olvida).{0,35}(instrucciones|instructions|reglas)|"
            r"(muestra|revela|dame|print|reveal).{0,45}(token|secret|\.env|system prompt)|"
            r"<\|(?:system|im_start|start_header_id)\|>",
            normalize(text),
        )
    )


def redact(text: str) -> str:
    def hide_number(match):
        value = match.group().strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}-\d{4}", value):
            return match.group()
        return "[número omitido]" if len(re.sub(r"\D", "", value)) >= 10 else match.group()

    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[correo omitido]", text)
    text = re.sub(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)", hide_number, text)
    text = re.sub(
        r"\b(?:gsk_|sk-)[A-Za-z0-9_-]{16,}\b|\bEAA[A-Za-z0-9]{30,}\b", "[credencial omitida]", text
    )
    return text
