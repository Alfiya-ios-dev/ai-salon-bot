import re
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class TenantBase(DeclarativeBase):
    """Declarative base for tenant-scoped tables (app/models.py) — Dialog,
    Message, Service, Staff, Booking, SalesPrompt, etc. These live in a
    separate physical database per tenant, NOT in tenant_registry_db (see
    app/database.py for that).
    """


DATABASE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


def _tenant_database_url(database_name: str) -> str:
    """Builds a connection URL for one tenant's database, reusing the
    host/port/credentials from settings.DATABASE_URL (the registry
    connection) and swapping in just the database name."""
    if not DATABASE_NAME_PATTERN.match(database_name):
        # Defense in depth: database_name ends up in raw DDL below (Postgres
        # doesn't support parameterized identifiers), so anything that could
        # be user-influenced is validated against a strict slug shape first.
        raise ValueError(f"Invalid database_name: {database_name!r}")
    parts = urlsplit(settings.DATABASE_URL)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, parts.fragment))


# One AsyncEngine (connection pool) per tenant database, created lazily and
# reused across requests — the same pattern as a single global engine, just
# keyed by database_name instead of there being only one.
_engines: dict[str, AsyncEngine] = {}
_sessionmakers: dict[str, async_sessionmaker[AsyncSession]] = {}


def get_tenant_engine(database_name: str) -> AsyncEngine:
    engine = _engines.get(database_name)
    if engine is None:
        engine = create_async_engine(_tenant_database_url(database_name), echo=False)
        _engines[database_name] = engine
    return engine


def get_tenant_sessionmaker(database_name: str) -> async_sessionmaker[AsyncSession]:
    sessionmaker = _sessionmakers.get(database_name)
    if sessionmaker is None:
        sessionmaker = async_sessionmaker(
            get_tenant_engine(database_name), class_=AsyncSession, expire_on_commit=False
        )
        _sessionmakers[database_name] = sessionmaker
    return sessionmaker


async def provision_tenant_database(database_name: str) -> None:
    """Physically creates a new Postgres database for a tenant and rolls out
    the full tenant schema (TenantBase.metadata) inside it.

    CREATE DATABASE can't run inside a transaction block, hence the
    AUTOCOMMIT connection used just to issue that one statement.
    """
    if not DATABASE_NAME_PATTERN.match(database_name):
        raise ValueError(f"Invalid database_name: {database_name!r}")

    admin_engine = create_async_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        await admin_engine.dispose()

    # Imported here (not at module top) to avoid a circular import —
    # app/models.py imports TenantBase from this module, so this module
    # can't import app.models at the top level. By the time this function
    # actually runs, app.models will already be registering its classes on
    # TenantBase.metadata via this same import.
    from app import models  # noqa: F401

    tenant_engine = get_tenant_engine(database_name)
    async with tenant_engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)


async def drop_tenant_database(database_name: str) -> None:
    """Irreversibly drops a tenant's entire database. Used by reset scripts,
    never by application request handlers."""
    if not DATABASE_NAME_PATTERN.match(database_name):
        raise ValueError(f"Invalid database_name: {database_name!r}")

    existing_engine = _engines.pop(database_name, None)
    _sessionmakers.pop(database_name, None)
    if existing_engine is not None:
        await existing_engine.dispose()

    admin_engine = create_async_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            # Terminate other backends first — DROP DATABASE fails while any
            # connection (e.g. a pooled one from this same process) is open.
            # text()/execute() (not exec_driver_sql) so :name goes through
            # SQLAlchemy's own parameter binding — asyncpg's driver-level
            # paramstyle doesn't understand ":name" placeholders directly.
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await admin_engine.dispose()
