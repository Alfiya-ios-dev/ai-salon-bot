from dataclasses import dataclass

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.registry_models import Tenant, TenantDialog

# Fires the "5 dialogs left" warning exactly when the count crosses this
# threshold. used_dialogs_count only ever increases by 1 at a time (once per
# genuinely new client), so this boundary is crossed at most once per tenant.
WARNING_THRESHOLD = 35

# Dialog.escalation_reason value set on dialogs created after their tenant's
# pilot cap was reached. Shared between message_intake.py (sets it) and
# pipeline.py (checks it to skip the AI entirely) — lives here rather than
# in either of those to avoid a message_intake <-> pipeline import cycle.
PILOT_LIMIT_REASON = "pilot_limit_reached"


@dataclass
class PilotLimitStatus:
    is_new_client: bool
    used_dialogs_count: int
    max_dialogs_limit: int
    is_pilot_active: bool
    # True once used_dialogs_count has reached/passed max_dialogs_limit (and
    # is_pilot_active is still on) — callers should stop routing this
    # dialog to the AI and hand it to a human instead.
    limit_reached: bool


async def notify_pilot_limit_warning(tenant: Tenant) -> None:
    """Alerts that a tenant is approaching its pilot dialog cap.

    There's no SMTP/SMS integration anywhere in this project, so "warn the
    business owner on their registration phone/email/Telegram" and "alert
    dalfy admins" are both satisfied today by a clearly-tagged log line
    (the owner's contact details are included, so this is ready to wire
    into a real notifier later without touching call sites). If
    DALFY_ADMIN_TELEGRAM_CHAT_ID is configured, a real Telegram message is
    also sent to dalfy's own admin chat via TELEGRAM_BOT_TOKEN.
    """
    remaining = tenant.max_dialogs_limit - tenant.used_dialogs_count
    message = (
        f"[PILOT_LIMIT] Tenant id={tenant.id} '{tenant.business_name}' "
        f"(email={tenant.email}, phone={tenant.business_phone_number}) has used "
        f"{tenant.used_dialogs_count}/{tenant.max_dialogs_limit} pilot dialogs — "
        f"{remaining} remaining before the bot stops answering new clients."
    )
    print(message, flush=True)

    if settings.DALFY_ADMIN_TELEGRAM_CHAT_ID and settings.TELEGRAM_BOT_TOKEN:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url, json={"chat_id": settings.DALFY_ADMIN_TELEGRAM_CHAT_ID, "text": message}
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"[PILOT_LIMIT] Failed to notify dalfy admin Telegram chat: {exc}", flush=True)


async def register_client_and_check_limit(
    registry_db: AsyncSession, tenant_id: int, client_external_id: str
) -> PilotLimitStatus:
    """Records client_external_id as having messaged this tenant, if it
    hasn't already, incrementing Tenant.used_dialogs_count exactly once per
    unique client — and reports whether the tenant's pilot cap is reached,
    so callers can stop routing this dialog to the AI.

    Race-safe: relies on TenantDialog's (tenant_id, client_external_id)
    unique constraint rather than a check-then-insert, so two
    near-simultaneous first messages from the same brand-new client can't
    both count.
    """
    tenant = await registry_db.get(Tenant, tenant_id)

    registry_db.add(TenantDialog(tenant_id=tenant_id, client_external_id=client_external_id))
    try:
        await registry_db.flush()
        is_new_client = True
    except IntegrityError:
        # Already-seen client (or a concurrent request just inserted it) —
        # the rollback expires `tenant`, so it's re-fetched below.
        await registry_db.rollback()
        is_new_client = False
        tenant = await registry_db.get(Tenant, tenant_id)

    if is_new_client:
        tenant.used_dialogs_count += 1
        await registry_db.commit()

    limit_reached = tenant.is_pilot_active and tenant.used_dialogs_count >= tenant.max_dialogs_limit

    if is_new_client and tenant.used_dialogs_count == WARNING_THRESHOLD:
        await notify_pilot_limit_warning(tenant)

    return PilotLimitStatus(
        is_new_client=is_new_client,
        used_dialogs_count=tenant.used_dialogs_count,
        max_dialogs_limit=tenant.max_dialogs_limit,
        is_pilot_active=tenant.is_pilot_active,
        limit_reached=limit_reached,
    )
