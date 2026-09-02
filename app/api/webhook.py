from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.registry_models import Tenant
from app.schemas import WebhookAck, WebhookRequest
from app.services.message_intake import ingest_client_message

router = APIRouter()

# Guardrail for non-text input: the bot has no way to interpret voice notes,
# audio, photos, video, documents, or stickers, so those get this canned
# reply immediately — no AI call and no DB write (no dialog/message row is
# ever created for them).
UNSUPPORTED_MEDIA_REPLY = (
    "Извините, я пока работаю только с текстовыми сообщениями и еще не умею "
    "распознавать голосовые, фото или видео 😊 Напишите, пожалуйста, ваш вопрос текстом!"
)


@router.post("/api/v1/webhook", response_model=WebhookAck)
async def receive_webhook(payload: WebhookRequest, registry_db: AsyncSession = Depends(get_db)):
    print(
        f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 📥 INCOMING WEBHOOK: "
        f"business_phone_number={payload.business_phone_number}, message_id={payload.message.message_id}, "
        f"type={payload.message.message_type}, text='{payload.message.text}'",
        flush=True,
    )

    # Media guardrail: anything that isn't plain text gets an immediate
    # canned reply and stops right here — no tenant lookup, no dialog/message
    # row, no AI call.
    if payload.message.message_type != "text":
        return WebhookAck(
            status="unsupported_media",
            message_id=payload.message.message_id,
            reply=UNSUPPORTED_MEDIA_REPLY,
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

    await ingest_client_message(
        tenant_id=tenant.id,
        database_name=tenant.database_name,
        client_external_id=payload.client_external_id,
        channel=payload.channel,
        message_id=payload.message.message_id,
        text=payload.message.text,
        timestamp=payload.message.timestamp,
    )

    return WebhookAck(status="received", message_id=payload.message.message_id)
