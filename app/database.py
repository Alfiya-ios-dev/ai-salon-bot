from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# This is the connection to tenant_registry_db — the one well-known,
# shared database that tracks which businesses (tenants) exist and which
# physical database each one's actual data (dialogs, bookings, services...)
# lives in. Tenant data itself is NOT here — see app/tenant_db.py for the
# per-tenant connection factory and app/models.py for the tenant-side schema.
engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for the registry DB only (app/registry_models.py)."""


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
