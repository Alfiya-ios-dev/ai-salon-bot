import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Dialog, DialogStatus, Message, SenderType
from app.registry_models import Tenant
from app.schemas import WebhookAck, WebhookRequest
from app.services import pipeline
from app.tenant_db import get_tenant_sessionmaker

router = APIRouter()

# In-memory per-client debounce buffers, keyed by (database_name, client_external_id)
# — client_external_id is only guaranteed unique *within* one tenant's own
# database (see Dialog.client_external_id's unique constraint there), so two
# different businesses whose clients happen to share an external id (e.g.
# the same phone number messaging two different salons) must never share a
# buffer. database_name is what actually identifies the isolated tenant
# database being written to, so it's the right key (not business_phone_number,
# which is just how we looked the tenant up).
# Each entry: {"messages": list[str], "task": asyncio.Task | None, "dialog_id": int}.
# Single-process only: a multi-worker deployment needs a shared store (e.g. Redis).
pending_buffers: dict[tuple[str, str], dict] = {}

# One lock per (database_name, client_external_id), serializing the dialog
# get-or-create check so two near-simultaneous first messages from a brand-new
# client can't both see "no dialog yet" and each insert their own row. Same
# single-process caveat as pending_buffers above.
_dialog_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _get_dialog_lock(database_name: str, client_external_id: str) -> asyncio.Lock:
    key = (database_name, client_external_id)
    lock = _dialog_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _dialog_locks[key] = lock
    return lock


async def _flush_after_silence(database_name: str, client_external_id: str) -> None:
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


def _schedule_debounced_reply(database_name: str, client_external_id: str, dialog_id: int, text: str) -> None:
    buffer_key = (database_name, client_external_id)
    buffer = pending_buffers.setdefault(buffer_key, {"messages": [], "task": None, "dialog_id": dialog_id})
    buffer["messages"].append(text)
    buffer["dialog_id"] = dialog_id

    existing_task = buffer["task"]
    if existing_task is not None and not existing_task.done():
        existing_task.cancel()

    buffer["task"] = asyncio.create_task(_flush_after_silence(database_name, client_external_id))


@router.post("/api/v1/webhook", response_model=WebhookAck)
async def receive_webhook(payload: WebhookRequest, registry_db: AsyncSession = Depends(get_db)):
    print(
        f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 📥 INCOMING WEBHOOK: "
        f"business_phone_number={payload.business_phone_number}, message_id={payload.message.message_id}, text='{payload.message.text}'",
        flush=True,
    )

    # Figure out which business this message is for, purely from the
    # WhatsApp number the client texted — that's the only tenant identifier
    # an inbound webhook carries.
    tenant = await registry_db.scalar(
        select(Tenant).where(Tenant.business_phone_number == payload.business_phone_number)
    )
    if tenant is None:
        raise HTTPException(
            status_code=404,
            detail=f"No business registered for business_phone_number '{payload.business_phone_number}'",
        )
    database_name = tenant.database_name

    tenant_sessionmaker = get_tenant_sessionmaker(database_name)

    # Held until commit: a second request for the same brand-new client must
    # wait for the first request's INSERT to actually land before it runs its
    # own SELECT, otherwise both see "no dialog yet" and create duplicates.
    async with _get_dialog_lock(database_name, payload.client_external_id):
        async with tenant_sessionmaker() as db:
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
    _schedule_debounced_reply(database_name, payload.client_external_id, dialog_id, payload.message.text)

    return WebhookAck(status="received", message_id=payload.message.message_id)
