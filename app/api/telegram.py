from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.registry_models import Tenant
from app.services.message_intake import ingest_client_message

router = APIRouter()

# Same wording as app/api/webhook.py's WhatsApp guardrail — the bot can't
# interpret voice notes, photos, video, documents, or stickers on any
# channel yet.
UNSUPPORTED_MEDIA_REPLY = (
    "Извините, я пока работаю только с текстовыми сообщениями и еще не умею "
    "распознавать голосовые, фото или видео 😊 Напишите, пожалуйста, ваш вопрос текстом!"
)


async def _send_telegram_message(bot_token: str, chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"[TELEGRAM] Failed to send message to chat {chat_id}: {exc}", flush=True)


@router.post("/{bot_token}")
async def receive_telegram_update(bot_token: str, request: Request) -> dict:
    """Telegram delivers webhook updates to whatever URL setWebhook was
    pointed at, with no bot-identifying field in the payload itself — so
    the bot token is embedded in the URL path and used here to look up
    which tenant this update belongs to (mirrors business_phone_number for
    the WhatsApp webhook in app/api/webhook.py). A tenant links its token
    via PUT /api/v1/auth/telegram-bot-token.
    """
    update = await request.json()
    print(f"[TELEGRAM] Incoming update: {update}", flush=True)

    message = update.get("message") or update.get("edited_message")
    if message is None:
        # Non-message updates (callback_query, channel_post, ...) — still
        # must return 200 or Telegram will keep retrying this update.
        return {"ok": True}

    async with AsyncSessionLocal() as registry_db:
        tenant = await registry_db.scalar(select(Tenant).where(Tenant.telegram_bot_token == bot_token))
    if tenant is None:
        raise HTTPException(status_code=404, detail="No business linked to this Telegram bot token")

    chat_id = message["chat"]["id"]
    client_external_id = str(chat_id)
    message_id = str(message["message_id"])

    # Media guardrail: anything without a "text" field (voice/photo/video/
    # document/sticker/...) gets an immediate canned reply — no dialog/
    # message row, no AI call. Sent directly via the Bot API since, unlike
    # the WhatsApp webhook, there's no other channel delivering the ack
    # back to the client.
    text = message.get("text")
    if text is None:
        await _send_telegram_message(bot_token, chat_id, UNSUPPORTED_MEDIA_REPLY)
        return {"ok": True}

    timestamp = datetime.fromtimestamp(message["date"], tz=timezone.utc)

    await ingest_client_message(
        database_name=tenant.database_name,
        client_external_id=client_external_id,
        channel="telegram",
        message_id=message_id,
        text=text,
        timestamp=timestamp,
        on_reply=lambda reply_text: _send_telegram_message(bot_token, chat_id, reply_text),
    )
    return {"ok": True}
