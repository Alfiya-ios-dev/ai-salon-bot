import asyncio
import uuid
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import select

from app.config import settings
from app.models import Dialog, DialogStatus, Message, SenderType
from app.services import pipeline
from app.tenant_db import get_tenant_sessionmaker

# Called with the bot's reply text once the debounce timer fires and the
# pipeline produces one. Channels that deliver the reply another way (e.g.
# WhatsApp via n8n reading the messages table) can leave this as None;
# channels that require an explicit outbound call (Telegram's sendMessage)
# pass one in.
ReplyCallback = Callable[[str], Awaitable[None]]

# In-memory per-client debounce buffers, keyed by (database_name,
# client_external_id) — client_external_id is only guaranteed unique
# *within* one tenant's own database (see Dialog.client_external_id's
# unique constraint there), so two different businesses whose clients
# happen to share an external id (e.g. the same Telegram user id or phone
# number messaging two different businesses) must never share a buffer.
# Shared across every inbound channel that funnels through
# ingest_client_message() below (WhatsApp webhook, Telegram webhook, ...).
# Each entry: {"messages": list[str], "task": asyncio.Task | None, "dialog_id": int}.
# Single-process only: a multi-worker deployment needs a shared store (e.g. Redis).
pending_buffers: dict[tuple[str, str], dict] = {}

# One lock per (database_name, client_external_id), serializing the dialog
# get-or-create check so two near-simultaneous first messages from a
# brand-new client can't both see "no dialog yet" and each insert their own
# row. Same single-process caveat as pending_buffers above.
_dialog_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _get_dialog_lock(database_name: str, client_external_id: str) -> asyncio.Lock:
    key = (database_name, client_external_id)
    lock = _dialog_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _dialog_locks[key] = lock
    return lock


async def _flush_after_silence(
    database_name: str, client_external_id: str, on_reply: ReplyCallback | None
) -> None:
    buffer_key = (database_name, client_external_id)
    try:
        await asyncio.sleep(settings.DEBOUNCE_DELAY_SECONDS)
    except asyncio.CancelledError:
        # A newer message arrived and restarted the timer; that task owns the flush now.
        return

    buffer = pending_buffers.pop(buffer_key, None)
    if buffer is None or not buffer["messages"]:
        return

    combined_text = "\n".join(buffer["messages"])

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🚀 [DEBOUNCE TRIGGERED] for db={database_name} client={client_external_id}", flush=True)
    print(f"\n=== [DEBOUNCE TRIGGERED] ===", flush=True)
    print(f"Database: {database_name}  Client: {client_external_id}", flush=True)
    print(f"Combined Text for AI (Total 1 call):", flush=True)
    print(combined_text, flush=True)
    print(f"============================\n", flush=True)

    # Serializes actual AI-reply generation per dialog: if a client sends a
    # second message more than DEBOUNCE_DELAY_SECONDS after the first (but
    # before the first flush's AI call has finished — a slow tool-calling
    # round-trip, say), that second message gets its own independent flush
    # task. Without this lock the two flushes would call the AI concurrently
    # for the same dialog — one of them loading history mid-write by the
    # other, which broke in testing (a request ending up with a malformed
    # trailing-assistant-turn history the model rejects). The lock makes the
    # second flush simply wait for the first to finish and commit before it
    # loads history of its own, so it always sees a consistent, correctly
    # user-terminated conversation. save_client_message() already persisted
    # this buffer's messages at ingestion time (before debounce), so nothing
    # here is lost by waiting.
    async with _get_dialog_lock(database_name, client_external_id):
        tenant_sessionmaker = get_tenant_sessionmaker(database_name)
        async with tenant_sessionmaker() as db:
            reply_text = await pipeline.handle_message(
                db, dialog_id=buffer["dialog_id"], combined_text=combined_text
            )
            if reply_text is not None:
                db.add(
                    Message(
                        message_id=f"bot-{uuid.uuid4()}",
                        dialog_id=buffer["dialog_id"],
                        sender_type=SenderType.bot,
                        text=reply_text,
                    )
                )
            await db.commit()

    if reply_text is not None and on_reply is not None:
        await on_reply(reply_text)


def schedule_debounced_reply(
    database_name: str,
    client_external_id: str,
    dialog_id: int,
    text: str,
    on_reply: ReplyCallback | None = None,
) -> None:
    buffer_key = (database_name, client_external_id)
    buffer = pending_buffers.setdefault(buffer_key, {"messages": [], "task": None, "dialog_id": dialog_id})
    buffer["messages"].append(text)
    buffer["dialog_id"] = dialog_id

    existing_task = buffer["task"]
    if existing_task is not None and not existing_task.done():
        existing_task.cancel()

    buffer["task"] = asyncio.create_task(
        _flush_after_silence(database_name, client_external_id, on_reply)
    )


async def save_client_message(
    *,
    database_name: str,
    client_external_id: str,
    channel: str,
    message_id: str,
    text: str,
    timestamp: datetime | None = None,
) -> int:
    """Get-or-creates the dialog and saves the client's message (idempotent
    on message_id) inside this tenant's own database. Returns dialog_id.

    Held under a per-(database_name, client_external_id) lock: a second
    call for the same brand-new client must wait for the first call's
    INSERT to actually land before running its own SELECT, otherwise both
    see "no dialog yet" and create duplicate dialogs.
    """
    tenant_sessionmaker = get_tenant_sessionmaker(database_name)
    async with _get_dialog_lock(database_name, client_external_id):
        async with tenant_sessionmaker() as db:
            result = await db.execute(
                select(Dialog).where(Dialog.client_external_id == client_external_id)
            )
            dialog = result.scalar_one_or_none()

            if dialog is None:
                dialog = Dialog(
                    client_external_id=client_external_id,
                    channel=channel,
                    language="ru",
                    status=DialogStatus.bot_active,
                )
                db.add(dialog)
                await db.flush()

            existing_message = await db.execute(select(Message).where(Message.message_id == message_id))
            if existing_message.scalar_one_or_none() is None:
                message_kwargs = {
                    "message_id": message_id,
                    "dialog_id": dialog.dialog_id,
                    "sender_type": SenderType.client,
                    "text": text,
                }
                if timestamp is not None:
                    message_kwargs["timestamp"] = timestamp
                db.add(Message(**message_kwargs))

            await db.commit()
            return dialog.dialog_id


async def ingest_client_message(
    *,
    database_name: str,
    client_external_id: str,
    channel: str,
    message_id: str,
    text: str,
    timestamp: datetime | None = None,
    on_reply: ReplyCallback | None = None,
) -> int:
    """Saves the client's message and schedules the debounced AI reply.
    Returns dialog_id.

    No await on the debounce timer here — scheduling it is a synchronous,
    fire-and-forget call, so HTTP webhook handlers can return their ack
    immediately instead of blocking for DEBOUNCE_DELAY_SECONDS.
    """
    dialog_id = await save_client_message(
        database_name=database_name,
        client_external_id=client_external_id,
        channel=channel,
        message_id=message_id,
        text=text,
        timestamp=timestamp,
    )
    schedule_debounced_reply(database_name, client_external_id, dialog_id, text, on_reply=on_reply)
    return dialog_id
