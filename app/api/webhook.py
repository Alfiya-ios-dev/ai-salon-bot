import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models import Dialog, DialogStatus, Message, SenderType
from app.schemas import WebhookAck, WebhookRequest
from app.services import pipeline

router = APIRouter()

# In-memory per-client debounce buffers, keyed by client_external_id (known
# synchronously from the payload, unlike dialog_id which requires a DB
# round-trip and was racy for a brand-new client's first two messages).
# Each entry: {"messages": list[str], "task": asyncio.Task | None, "dialog_id": int}.
# Single-process only: a multi-worker deployment needs a shared store (e.g. Redis).
pending_buffers: dict[str, dict] = {}

# One lock per client_external_id, serializing the dialog get-or-create check
# so two near-simultaneous first messages from a brand-new client can't both
# see "no dialog yet" and each insert their own row. Same single-process
# caveat as pending_buffers above.
_dialog_locks: dict[str, asyncio.Lock] = {}


def _get_dialog_lock(client_external_id: str) -> asyncio.Lock:
    lock = _dialog_locks.get(client_external_id)
    if lock is None:
        lock = asyncio.Lock()
        _dialog_locks[client_external_id] = lock
    return lock


async def _flush_after_silence(client_external_id: str) -> None:
    try:
        await asyncio.sleep(settings.DEBOUNCE_DELAY_SECONDS)
    except asyncio.CancelledError:
        # A newer message arrived and restarted the timer; that task owns the flush now.
        return

    buffer = pending_buffers.pop(client_external_id, None)
    if buffer is None or not buffer["messages"]:
        return

    combined_text = "\n".join(buffer["messages"])

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🚀 [DEBOUNCE TRIGGERED] for client {client_external_id}", flush=True)
    print(f"\n=== [DEBOUNCE TRIGGERED] ===", flush=True)
    print(f"Client: {client_external_id}", flush=True)
    print(f"Combined Text for AI (Total 1 call):", flush=True)
    print(combined_text, flush=True)
    print(f"============================\n", flush=True)

    async with AsyncSessionLocal() as db:
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


def _schedule_debounced_reply(client_external_id: str, dialog_id: int, text: str) -> None:
    buffer = pending_buffers.setdefault(
        client_external_id, {"messages": [], "task": None, "dialog_id": dialog_id}
    )
    buffer["messages"].append(text)
    buffer["dialog_id"] = dialog_id

    existing_task = buffer["task"]
    if existing_task is not None and not existing_task.done():
        existing_task.cancel()

    buffer["task"] = asyncio.create_task(_flush_after_silence(client_external_id))


@router.post("/api/v1/webhook", response_model=WebhookAck)
async def receive_webhook(payload: WebhookRequest, db: AsyncSession = Depends(get_db)):
    print(
        f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 📥 INCOMING WEBHOOK: "
        f"message_id={payload.message.message_id}, text='{payload.message.text}'",
        flush=True,
    )

    # Held until commit: a second request for the same brand-new client must
    # wait for the first request's INSERT to actually land before it runs its
    # own SELECT, otherwise both see "no dialog yet" and create duplicates.
    async with _get_dialog_lock(payload.client_external_id):
        result = await db.execute(
            select(Dialog).where(Dialog.client_external_id == payload.client_external_id)
        )
        dialog = result.scalar_one_or_none()

        if dialog is None:
            dialog = Dialog(
                client_external_id=payload.client_external_id,
                channel=payload.channel,
                language="ru",
                status=DialogStatus.bot_active,
            )
            db.add(dialog)
            await db.flush()

        existing_message = await db.execute(
            select(Message).where(Message.message_id == payload.message.message_id)
        )
        if existing_message.scalar_one_or_none() is None:
            db.add(
                Message(
                    message_id=payload.message.message_id,
                    dialog_id=dialog.dialog_id,
                    sender_type=SenderType.client,
                    text=payload.message.text,
                    timestamp=payload.message.timestamp,
                )
            )

        await db.commit()
        dialog_id = dialog.dialog_id

    # No await on the debounce timer here — scheduling it is a synchronous,
    # fire-and-forget call, so this handler returns 200 immediately instead
    # of blocking the HTTP response for DEBOUNCE_DELAY_SECONDS.
    _schedule_debounced_reply(payload.client_external_id, dialog_id, payload.message.text)

    return WebhookAck(status="received", message_id=payload.message.message_id)
