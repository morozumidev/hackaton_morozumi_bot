import asyncio
import fcntl
import hashlib
import hmac
import json
import logging
import re
import time
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError

from bot.agent import Agent
from bot.config import Settings
from bot.providers import ChatAPI, Guards, WhatsApp
from bot.security import MAX_TEXT, owner_id, signature_valid
from bot.storage import Store

logger = logging.getLogger("morozumi")


class Text(BaseModel):
    body: str


class Incoming(BaseModel):
    id: str = Field(min_length=1, max_length=512)
    sender: str = Field(alias="from", pattern=r"^[0-9]{6,20}$")
    timestamp: str = Field(pattern=r"^[0-9]{1,12}$")
    type: str
    text: Text | None = None


async def process_next(store: Store, agent: Agent, whatsapp: WhatsApp) -> bool:
    job = store.next_job()
    if not job:
        return False
    try:
        result = job["response"]
        if result is None:
            result = await agent.reply(job["owner"], job["id"], job["body"])
            store.save_response(job["id"], result)
        await whatsapp.send(job["recipient"], result)
        store.complete(job["id"])
        logger.info("message_processed")
    except Exception:
        store.retry(job["id"], job["attempts"] + 1)
        logger.warning("message_retry_or_failed")
    return True


async def worker(store: Store, agent: Agent, whatsapp: WhatsApp):
    last_maintenance = 0.0
    while True:
        try:
            if time.monotonic() - last_maintenance > 60:
                store.maintain()
                last_maintenance = time.monotonic()
            if not await process_next(store, agent, whatsapp):
                await asyncio.sleep(0.3)
        except Exception:
            logger.warning("worker_error")
            await asyncio.sleep(2)


def create_app(settings: Settings | None = None, *, start_worker: bool = True):
    settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with settings.database.with_suffix(".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(
                    "Esta base de datos ya tiene un proceso del bot activo."
                ) from None
            store = Store(
                settings.database, settings.timezone, settings.slot_hours, settings.memory_ttl
            )
            app.state.store = store
            async with httpx.AsyncClient(timeout=settings.timeout, trust_env=False) as client:
                model = ChatAPI(client, settings.llm_url, settings.llm_model, settings.llm_key)
                agent = Agent(store, model, Guards(client, settings))
                task = (
                    asyncio.create_task(worker(store, agent, WhatsApp(client, settings)))
                    if start_worker
                    else None
                )
                app.state.worker = task
                try:
                    yield
                finally:
                    if task:
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task

    app = FastAPI(
        title="hackaton_morozumi_bot",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def health():
        task = app.state.worker
        if task is not None and task.done():
            raise HTTPException(503, "worker_unavailable")
        return {"status": "ok"}

    @app.get("/webhook", response_class=PlainTextResponse)
    async def verify(request: Request):
        params = request.query_params
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")
        if (
            params.get("hub.mode") != "subscribe"
            or not hmac.compare_digest(token.encode(), settings.verify_token.encode())
            or not re.fullmatch(r"[0-9]{1,100}", challenge)
        ):
            raise HTTPException(403, "verification_failed")
        return challenge

    @app.post("/webhook")
    async def webhook(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413, "payload_too_large")
        if not signature_valid(
            bytes(body), request.headers.get("x-hub-signature-256", ""), settings.app_secret
        ):
            raise HTTPException(403, "invalid_signature")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError
            if payload.get("object") != "whatsapp_business_account":
                return {"status": "ignored"}
            incoming = []
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    if (
                        change.get("field") != "messages"
                        or value.get("metadata", {}).get("phone_number_id") != settings.phone_id
                    ):
                        continue
                    incoming.extend(
                        Incoming.model_validate(message) for message in value.get("messages", [])
                    )
        except (ValueError, TypeError, AttributeError, ValidationError):
            raise HTTPException(400, "invalid_payload") from None
        for message in incoming:
            age = time.time() - int(message.timestamp)
            if age > 23 * 3600 or age < -300:
                continue
            text = message.text.body if message.type == "text" and message.text else ""
            response = None
            if not text:
                response = "Por ahora atiendo mensajes de texto. Escríbeme qué servicio u horario necesitas."
            elif len(text) > MAX_TEXT:
                response = f"Envíame un mensaje de máximo {MAX_TEXT} caracteres, por favor."
                text = ""
            event = hashlib.sha256(message.id.encode()).hexdigest()
            status = app.state.store.enqueue(
                event,
                owner_id(message.sender, settings.session_secret),
                message.sender,
                text,
                settings.rate_limit,
            )
            if status == "full":
                raise HTTPException(503, "queue_full")
            if status == "queued" and response:
                app.state.store.save_response(event, response)
            if status == "rate_limited":
                logger.info("rate_limited")
        return {"status": "ok"}

    return app
