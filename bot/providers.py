import math

import httpx

from bot.config import Settings


class RemoteError(Exception):
    pass


class ChatAPI:
    def __init__(self, client: httpx.AsyncClient, url: str, model: str, key: str = ""):
        self.client, self.url, self.model, self.key = client, url, model, key

    async def complete(self, messages: list, tools: list | None = None):
        payload = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload.update(tools=tools, temperature=0.2, max_tokens=500)
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        try:
            response = await self.client.post(
                self.url + "/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ValueError
            return message
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise RemoteError("El proveedor de modelos no respondió correctamente.") from None


class Guards:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.guard = ChatAPI(client, settings.guard_url, settings.guard_model, settings.guard_key)
        self.prompt_guard = (
            ChatAPI(
                client,
                "https://api.groq.com/openai/v1",
                settings.prompt_guard_model,
                settings.prompt_guard_key,
            )
            if settings.prompt_guard_key
            else None
        )

    async def content_safe(self, messages: list) -> bool:
        result = (await self.guard.complete(messages)).get("content", "")
        if not isinstance(result, str):
            raise RemoteError("Llama Guard devolvió una clasificación inválida.")
        label = result.strip().splitlines()
        if result.strip() == "safe":
            return True
        if label and label[0] == "unsafe":
            return False
        raise RemoteError("Llama Guard devolvió una clasificación inválida.")

    async def injection_safe(self, text: str) -> bool:
        if not self.prompt_guard:
            return True
        chunks, chunk = [], ""
        for char in text:
            if len((chunk + char).encode()) > 320:
                chunks.append(chunk)
                chunk = ""
            chunk += char
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            result = await self.prompt_guard.complete([{"role": "user", "content": chunk}])
            try:
                score = float(result["content"])
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise RemoteError("Prompt Guard devolvió una clasificación inválida.") from None
            if score >= 0.5:
                return False
        return True


class WhatsApp:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client, self.settings = client, settings

    async def send(self, recipient: str, message: str):
        s = self.settings
        try:
            response = await self.client.post(
                f"https://graph.facebook.com/{s.graph_version}/{s.phone_id}/messages",
                headers={"Authorization": f"Bearer {s.access_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": recipient,
                    "type": "text",
                    "text": {"body": message[:4000], "preview_url": False},
                },
            )
            response.raise_for_status()
            if not response.json().get("messages"):
                raise ValueError
        except (httpx.HTTPError, ValueError, AttributeError):
            raise RemoteError("WhatsApp no confirmó el envío.") from None
