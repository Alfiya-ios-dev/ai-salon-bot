"""Full factory reset under database-per-tenant: physically drops EVERY
tenant's own database (bookings, services, staff, dialogs, messages,
rag_documents, sales_prompts, everything), then clears the registry itself
(tenant_registry_db's `tenants` table) so no business — and none of its
data — is left anywhere.

Unlike scripts/clear_db.py (which only clears one specific tenant's
business-config tables and deliberately keeps that tenant's conversation
history), this is total: every tenant database in existence is dropped
outright. Use clear_db.py instead if you want to keep one tenant's chat
history while just reconfiguring its services/staff/prices.

DESTRUCTIVE AND IRREVERSIBLE. Requires typing a confirmation phrase unless
--yes is passed. Use --dry-run to only list tenants without deleting.

Usage:
    python scripts/reset_to_clean_slate.py             # prompts for confirmation
    python scripts/reset_to_clean_slate.py --dry-run   # only lists tenants
    python scripts/reset_to_clean_slate.py --yes       # skips the prompt (CI/automation)
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app import registry_models  # noqa: E402,F401  (registers Tenant on Base.metadata)
from app.registry_models import Tenant  # noqa: E402
from app.tenant_db import drop_tenant_database  # noqa: E402

CONFIRMATION_PHRASE = "ПОЛНЫЙ СБРОС"


async def _list_tenants() -> list[Tenant]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Tenant).order_by(Tenant.id))
        return list(result.scalars().all())


async def reset(dry_run: bool) -> None:
    tenants = await _list_tenants()
    print(f"Тенантов в реестре: {len(tenants)}")
    for tenant in tenants:
        print(f"  id={tenant.id}  business_name={tenant.business_name!r}  database={tenant.database_name}")

    if dry_run:
        print("\n--dry-run: изменения не вносились.")
        return

    for tenant in tenants:
        print(f"Удаление базы {tenant.database_name}...")
        await drop_tenant_database(tenant.database_name)

    async with engine.begin() as conn:
        await conn.execute(text('DROP TABLE IF EXISTS "tenants" CASCADE'))
        await conn.run_sync(Base.metadata.create_all)

    print(
        "\nГотово: все базы данных тенантов удалены, реестр (tenant_registry_db) "
        "пересоздан и полностью пуст. Можно регистрировать новые бизнесы через "
        "POST /api/v1/auth/register."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="Only list tenants, don't delete anything")
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        answer = input(
            "Это НЕОБРАТИМО удалит ВСЕ базы данных всех тенантов (бизнес, услуги, "
            "мастера, брони, диалоги, переписку, промпты) и очистит реестр — полный "
            f"сброс до чистого состояния.\nВведите '{CONFIRMATION_PHRASE}' для подтверждения: "
        )
        if answer.strip() != CONFIRMATION_PHRASE:
            print("Отменено.")
            return

    asyncio.run(reset(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
