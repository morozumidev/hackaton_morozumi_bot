import asyncio
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

from bot.app import process_next
from bot.storage import Store


def test_two_confirmations_cannot_book_the_same_slot(store):
    slot = store.available()[0]["id"]
    store.propose("a", slot, "corte")
    store.propose("b", slot, "barba")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda owner: store.command(owner, secrets.token_hex(16), "confirmar"), ["a", "b"]
            )
        )
    assert sum("Cita confirmada" in r for r in results) == 1
    assert len(store.bookings("a")) + len(store.bookings("b")) == 1


def test_confirmation_is_idempotent_and_survives_restart(store):
    store.propose("a", store.available()[0]["id"], "corte")
    event = secrets.token_hex(16)
    result = store.command("a", event, "confirmar")
    restarted = Store(store.path, store.zone.key, store.hours)
    assert restarted.command("a", event, "confirmar") == result
    assert len(restarted.bookings("a")) == 1


def test_expired_proposal_cannot_be_confirmed(store):
    store.propose("a", store.available()[0]["id"], "corte")
    with store.connect() as db:
        db.execute("UPDATE sessions SET pending=json_set(pending, '$.expires', 0)")
    assert "vigente" in store.command("a", secrets.token_hex(16), "confirmar")
    assert not store.bookings("a")


def test_retention_expires_memory_and_delivery_metadata(store):
    store.save_history("a", [{"role": "user", "content": "Hola"}])
    store.enqueue("old", "a", secrets.token_hex(16), "Hola", 10)
    with store.connect() as db:
        db.execute("UPDATE sessions SET updated=0")
        db.execute("UPDATE jobs SET created=0")
    store.maintain()
    assert store.session("a") == ([], None)
    assert store.counts() == {}


def test_delivery_failure_reuses_response_without_rebooking(store):
    event = secrets.token_hex(16)
    recipient = secrets.token_hex(16)
    store.enqueue(event, "a", recipient, "CONFIRMAR", 10)
    agent, whatsapp = AsyncMock(), AsyncMock()
    agent.reply.return_value = "Cita confirmada"
    whatsapp.send.side_effect = [RuntimeError(), None]
    assert asyncio.run(process_next(store, agent, whatsapp))
    with store.connect() as db:
        db.execute("UPDATE jobs SET next_try=0")
    assert asyncio.run(process_next(store, agent, whatsapp))
    assert agent.reply.call_count == 1
    assert whatsapp.send.call_count == 2
    assert store.counts() == {"done": 1}
    with store.connect() as db:
        row = db.execute("SELECT recipient, body, response FROM jobs").fetchone()
        assert tuple(row) == (None, None, None)


def test_retry_keeps_order_for_same_user(store):
    store.enqueue("first", "a", "a", "Hola", 10)
    store.enqueue("second", "a", "a", "Adiós", 10)
    store.enqueue("third", "b", "b", "Hola", 10)
    store.retry("first", 1)
    assert store.next_job()["id"] == "third"
    store.complete("third")
    assert store.next_job() is None
    with store.connect() as db:
        db.execute("UPDATE jobs SET next_try=? WHERE id='first'", (time.time() - 1,))
    assert store.next_job()["id"] == "first"


def test_permanent_delivery_failure_discards_content(store):
    store.enqueue("event", "a", "a", "Hola", 10)
    store.retry("event", 3)
    assert store.counts() == {"failed": 1}
    with store.connect() as db:
        assert db.execute("SELECT body FROM jobs").fetchone()[0] is None
