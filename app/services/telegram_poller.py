import asyncio

import httpx
from sqlalchemy import select

from app.api.telegram import process_telegram_message
from app.database import AsyncSessionLocal
from app.registry_models import Tenant

# getUpdates long-poll timeout (seconds) — Telegram holds the connection
# open and returns as soon as an update arrives, or after this many seconds
# with nothing. Kept well under POLL_INTERVAL_SECONDS' cycle budget so one
# slow bot with no traffic doesn't stall the others for long.
GETUPDATES_TIMEOUT = 20

# How often the whole tenant list is re-scanned for newly-linked bots.
POLL_INTERVAL_SECONDS = 3

# Fallback delivery path while no HTTPS/domain is set up for a real Telegram
# webhook (see app/api/telegram.py) — polls getUpdates for every tenant with
# a linked bot instead. Not mutually exclusive with a real webhook at the
# protocol level, but Telegram itself refuses to run both for the same bot
# (setWebhook errors out while getUpdates is in use, and vice versa), so
# this is meant to be temporary until a webhook can be registered.
_last_update_id: dict[str, int] = {}


async def _poll_one_bot(bot_token: str, tenant_id: int, database_name: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    offset = _last_update_id.get(bot_token, 0) + 1
    params = {"offset": offset, "timeout": GETUPDATES_TIMEOUT}
    try:
        async with httpx.AsyncClient(timeout=GETUPDATES_TIMEOUT + 10) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        print(f"[TELEGRAM_POLLER] getUpdates failed for tenant {tenant_id}: {exc}", flush=True)
        return

    if not data.get("ok"):
        print(f"[TELEGRAM_POLLER] getUpdates error for tenant {tenant_id}: {data}", flush=True)
        return

    for update in data.get("result", []):
        _last_update_id[bot_token] = update["update_id"]
        message = update.get("message") or update.get("edited_message")
        if message is None:
            continue
        print(f"[TELEGRAM_POLLER] Incoming message for tenant {tenant_id}: {message}", flush=True)

        async with AsyncSessionLocal() as registry_db:
            tenant = await registry_db.get(Tenant, tenant_id)
        if tenant is None or tenant.telegram_bot_token != bot_token:
            # Tenant was deleted or unlinked its bot mid-poll — drop this
            # update rather than crash the loop.
            continue

        try:
            await process_telegram_message(tenant, message)
        except Exception as exc:
            print(f"[TELEGRAM_POLLER] Failed to process update for tenant {tenant_id}: {exc}", flush=True)


async def run_telegram_polling_loop() -> None:
    """Background task (started from app.main's lifespan): repeatedly polls
    getUpdates for every tenant with a linked Telegram bot. Runs forever —
    cancelled on app shutdown.
    """
    print("[TELEGRAM_POLLER] Starting Telegram getUpdates polling loop", flush=True)
    while True:
        try:
            async with AsyncSessionLocal() as registry_db:
                result = await registry_db.execute(
                    select(Tenant.id, Tenant.telegram_bot_token, Tenant.database_name).where(
                        Tenant.telegram_bot_token.is_not(None)
                    )
                )
                bots = result.all()

            for tenant_id, bot_token, database_name in bots:
                await _poll_one_bot(bot_token, tenant_id, database_name)
        except asyncio.CancelledError:
            print("[TELEGRAM_POLLER] Stopping (app shutdown)", flush=True)
            raise
        except Exception as exc:
            print(f"[TELEGRAM_POLLER] Unexpected error in polling loop: {exc}", flush=True)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
