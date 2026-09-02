from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tenant(Base):
    """One row per business, living in tenant_registry_db. Points at (but
    does not contain) that business's actual data, which lives in its own
    separate `database_name` database — see app/tenant_db.py.
    """

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # The WhatsApp number clients message this business on — webhook.py uses
    # this to figure out which tenant an incoming message belongs to.
    business_phone_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    # Optional Telegram bot token linked via PUT /api/v1/auth/telegram-bot-token.
    # Telegram delivers webhook updates with no bot-identifying field in the
    # payload itself, so the token is embedded in the webhook URL path
    # (see app/api/telegram.py) and looked up here the same way
    # business_phone_number routes the WhatsApp webhook.
    telegram_bot_token: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    database_name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Pilot-period usage cap — see app/services/pilot_limit_service.py.
    # is_pilot_active gates enforcement entirely: flip to False (e.g. once a
    # tenant converts to a paid plan) to stop counting/blocking regardless of
    # used_dialogs_count.
    max_dialogs_limit: Mapped[int] = mapped_column(default=40)
    used_dialogs_count: Mapped[int] = mapped_column(default=0)
    is_pilot_active: Mapped[bool] = mapped_column(default=True)


class TenantDialog(Base):
    """One row per unique client a tenant has ever received a message from,
    used purely to count distinct pilot-period conversations exactly once
    each (see pilot_limit_service.register_client_and_check_limit) — not to
    be confused with the tenant's own per-database `dialogs` table
    (app/models.py), which holds the actual conversation.

    Lives in the registry DB (keyed by tenant_id) rather than inside each
    tenant's own database, because the 40-dialog cap is an account-level
    concept the registry already owns (max_dialogs_limit/used_dialogs_count
    on Tenant above).
    """

    __tablename__ = "tenant_dialogs"
    __table_args__ = (UniqueConstraint("tenant_id", "client_external_id", name="uq_tenant_dialog_client"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    # A phone number for WhatsApp, a Telegram chat id for Telegram — whatever
    # this tenant's Dialog.client_external_id is for the same client (see
    # app/models.py), kept as a string for both cases.
    client_external_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
