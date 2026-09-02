from datetime import datetime

from sqlalchemy import DateTime, String, func
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
