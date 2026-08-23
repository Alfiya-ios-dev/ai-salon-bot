"""Wipes one tenant's business-specific data so its database is a clean
slate for reconfiguring (e.g. before re-onboarding an existing pilot
client). Under database-per-tenant, each business has its own physical
database, so a tenant must be selected via --tenant-id.

Clears: business_info, services, staff, staff_schedule, bookings,
sales_prompts — plus staff_services, the many-to-many join table between
staff and services. It isn't one of the tables named in the request, but it
holds foreign keys into both staff and services, so it has to be cleared
alongside them or the TRUNCATE below would fail with a FK violation.

Deliberately does NOT touch dialogs/messages (conversation history) or
rag_documents (freeform knowledge-base docs) — those weren't asked for, and
a business being reconfigured may still want its conversation
infrastructure intact. Say so explicitly if you also want those wiped.

DESTRUCTIVE AND IRREVERSIBLE. Requires typing a confirmation phrase unless
--yes is passed. Use --dry-run to only see row counts without deleting.

Usage:
    python scripts/clear_db.py --tenant-id 3             # prompts for confirmation
    python scripts/clear_db.py --tenant-id 3 --dry-run   # only prints row counts, no changes
    python scripts/clear_db.py --tenant-id 3 --yes       # skips the prompt (CI/automation)
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app import registry_models  # noqa: E402,F401  (registers Tenant on Base.metadata)
from app.registry_models import Tenant  # noqa: E402
from app.tenant_db import get_tenant_engine  # noqa: E402

# Order doesn't matter for the TRUNCATE itself (listing all related tables
# in one statement handles the FK relationships between them), but it's
# still listed dependents-first for readability.
TABLES = [
    "bookings",
    "staff_services",
    "staff_schedule",
    "staff",
    "services",
    "business_info",
    "sales_prompts",
]

CONFIRMATION_PHRASE = "ОЧИСТИТЬ"


async def _resolve_tenant(tenant_id: int) -> Tenant:
    async with AsyncSessionLocal() as db:
        tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        print(f"Тенант с id={tenant_id} не найден в реестре.")
        sys.exit(1)
    return tenant


async def _row_counts(database_name: str) -> dict[str, int]:
    engine = get_tenant_engine(database_name)
    counts = {}
    async with engine.connect() as conn:
        for table in TABLES:
            result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            counts[table] = result.scalar()
    return counts


async def clear(tenant: Tenant, dry_run: bool) -> None:
    counts = await _row_counts(tenant.database_name)
    print(f"Тенант id={tenant.id} ({tenant.business_name!r}), database={tenant.database_name}")
    print("Таблицы и текущее количество строк:")
    for table, count in counts.items():
        print(f"  {table}: {count}")

    if dry_run:
        print("\n--dry-run: изменения не вносились.")
        return

    table_list = ", ".join(f'"{t}"' for t in TABLES)
    engine = get_tenant_engine(tenant.database_name)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY"))

    print(
        "\nГотово: business_info, services, staff, staff_services, staff_schedule, "
        "bookings, sales_prompts очищены и ID сброшены. "
        "dialogs/messages/rag_documents не тронуты."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", type=int, required=True, help="Registry id of the tenant to clear")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="Only print row counts, don't delete anything")
    args = parser.parse_args()

    tenant = asyncio.run(_resolve_tenant(args.tenant_id))

    if not args.dry_run and not args.yes:
        answer = input(
            f"Это НЕОБРАТИМО удалит все данные о бизнесе '{tenant.business_name}' (услуги, "
            f"мастера, график, брони, промпты) из базы {tenant.database_name}.\n"
            f"Введите '{CONFIRMATION_PHRASE}' для подтверждения: "
        )
        if answer.strip() != CONFIRMATION_PHRASE:
            print("Отменено.")
            return

    asyncio.run(clear(tenant, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
