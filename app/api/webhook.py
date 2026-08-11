from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Dialog, DialogStatus, Message, SenderType
from app.schemas import WebhookRequest, WebhookResponse

router = APIRouter()


@router.post("/api/v1/webhook", response_model=WebhookResponse)
async def receive_webhook(payload: WebhookRequest, db: AsyncSession = Depends(get_db)):
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

    return WebhookResponse(
        action="reply",
        channel=payload.channel,
        client_external_id=payload.client_external_id,
        text=f"Эхо: {payload.message.text}",
    )
