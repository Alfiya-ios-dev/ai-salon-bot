"""Data load for the Maratova Beauty Studio pilot tenant.

Idempotent: get-or-creates the "Maratova Beauty Studio" Tenant row in the
registry (registering it — including provisioning its own physical database
— if it doesn't exist yet), then seeds business info / staff / services /
schedule *inside that tenant's own database*, skipping anything that already
exists there. Safe to re-run.

Usage:
    python scripts/seed_maratova_beauty.py
"""

import asyncio
import sys
from datetime import date, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app import registry_models  # noqa: E402,F401  (registers Tenant on Base.metadata)
from app.models import (  # noqa: E402
    BusinessInfo,
    Service,
    Staff,
    StaffSchedule,
    StaffService,
)
from app.registry_models import Tenant  # noqa: E402
from app.services.auth_service import hash_password  # noqa: E402
from app.tenant_db import get_tenant_sessionmaker, provision_tenant_database  # noqa: E402

TENANT_NAME = "Maratova Beauty Studio"
# Local/dev seed credentials only — not meant for a real production signup.
TENANT_EMAIL = "owner@maratovabeauty.example.com"
TENANT_PASSWORD = "change-me-12345"
TENANT_PHONE = "+996700000001"

SCHEDULE_DAYS_AHEAD = 30
WORK_START = time(9, 0)
WORK_END = time(21, 0)

BUSINESS_INFO = {
    "name": "Maratova Beauty Studio",
    "address": "г. Бишкек, ул. Радищева, 28, Baytik Tower, 6-й этаж, каб. 603",
    "working_hours": "09:00 - 21:00, без выходных",
}

STAFF = [
    {"name": "Тумар", "role": "Nail-мастер"},
    {"name": "Бени", "role": "Nail-мастер"},
    {"name": "Айдана", "role": "Nail-мастер"},
    {"name": "Гульнара", "role": "Lash-мастер / Бровист"},
]

NAIL_STAFF = ["Тумар", "Бени", "Айдана"]
LASH_STAFF = ["Гульнара"]
ALL_STAFF = [s["name"] for s in STAFF]

NAIL_SERVICES = [
    ("Гигиенический маникюр", 800, 60),
    ("Японский маникюр", 1200, 60),
    ("Маникюр «все включено»", 1600, 90),
    ("Наращивание ногтей до 3 длины", 2000, 120),
    ("Наращивание ногтей 3-6 длина", 2500, 150),
    ("Коррекция наращивания", 1800, 120),
    ("Smart педикюр гигиенический", 1500, 60),
    ("Smart педикюр с покрытием", 2000, 90),
    ("Пальчики + покрытие", 1600, 60),
    ("Покрытие обычным лаком", 200, 20),
    ("Донаращивание 1 ногтя", 200, 20),
    ("Ремонт 1 ногтя", 100, 15),
    ("Френч / омбре / втирка", 200, 30),
    ("Снятие гель-лака без покрытия", 300, 30),
    ("Снятие нарощенных ногтей без покрытия", 400, 30),
    ("Снятие нарощенных ногтей с покрытием", 300, 30),
]

LASH_BROW_SERVICES = [
    ("Классический объем 1D", 1500, 120),
    ("Полуторный объем 1.5D", 1600, 120),
    ("Объем 2D", 1800, 120),
    ("Объем 3D", 2000, 150),
    ("Нижние ресницы", 1000, 60),
    ("Снятие ресниц без наращивания", 200, 30),
    ("Коррекция бровей", 500, 30),
    ("Покраска бровей", 500, 30),
    ("Ламинирование ресниц", 1400, 60),
    ("Ламинирование бровей без покраски", 1000, 45),
    ("Ламинирование бровей с покраской и коррекцией", 1800, 60),
]

COMBO_SERVICES = [
    ("Комплекс 2в1 #1 Маникюр + Педикюр", 3200, 120),
    ("Комплекс 2в1 #2 Ресницы до 3D + Маникюр", 3200, 150),
    ("Комплекс 2в1 Natural Маникюр + Педикюр", 2300, 90),
    ("Beauty Set VIP 3в1 Ресницы + Маникюр + Педикюр", 4800, 180),
    ("Beauty Set Natural 3в1 Ресницы + Маникюр + Педикюр", 3800, 150),
]

# Each entry: (category label, service tuples, which staff (by name) offer them)
SERVICE_GROUPS = [
    ("Ногтевой сервис", NAIL_SERVICES, NAIL_STAFF),
    ("Ресницы и брови", LASH_BROW_SERVICES, LASH_STAFF),
    ("Комплексы", COMBO_SERVICES, ALL_STAFF),
]


async def _get_or_create_tenant() -> Tenant:
    async with AsyncSessionLocal() as db:
        tenant = await db.scalar(select(Tenant).where(Tenant.business_name == TENANT_NAME))
        if tenant is not None:
            return tenant

        tenant = Tenant(
            business_name=TENANT_NAME,
            email=TENANT_EMAIL,
            password_hash=hash_password(TENANT_PASSWORD),
            business_phone_number=TENANT_PHONE,
            database_name="pending",
        )
        db.add(tenant)
        await db.flush()
        tenant.database_name = f"tenant_{tenant.id}_db"
        await provision_tenant_database(tenant.database_name)
        await db.commit()
        await db.refresh(tenant)
        return tenant


async def seed() -> None:
    # Registry schema must exist before we can look up/insert the tenant row.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tenant = await _get_or_create_tenant()
    sessionmaker = get_tenant_sessionmaker(tenant.database_name)

    async with sessionmaker() as db:
        for key, value in BUSINESS_INFO.items():
            existing = await db.get(BusinessInfo, key)
            if existing is None:
                db.add(BusinessInfo(key=key, value=value))

        staff_by_name: dict[str, Staff] = {}
        for staff_data in STAFF:
            existing = await db.scalar(select(Staff).where(Staff.name == staff_data["name"]))
            if existing is None:
                existing = Staff(**staff_data)
                db.add(existing)
                await db.flush()
            staff_by_name[staff_data["name"]] = existing

        await db.commit()

        service_count = 0
        for category, services, staff_names in SERVICE_GROUPS:
            for name, price, duration_minutes in services:
                service = await db.scalar(select(Service).where(Service.name == name))
                if service is None:
                    service = Service(
                        category=category,
                        name=name,
                        price=price,
                        duration_minutes=duration_minutes,
                    )
                    db.add(service)
                    await db.flush()  # need service.id for the StaffService links below
                service_count += 1

                for staff_name in staff_names:
                    staff = staff_by_name[staff_name]
                    link = await db.scalar(
                        select(StaffService).where(
                            StaffService.staff_id == staff.id, StaffService.service_id == service.id
                        )
                    )
                    if link is None:
                        db.add(StaffService(staff_id=staff.id, service_id=service.id))

        await db.commit()

        schedule_count = 0
        for staff in staff_by_name.values():
            for day_offset in range(SCHEDULE_DAYS_AHEAD):
                schedule_date = date.today() + timedelta(days=day_offset)
                existing = await db.scalar(
                    select(StaffSchedule).where(
                        StaffSchedule.staff_id == staff.id, StaffSchedule.date == schedule_date
                    )
                )
                if existing is None:
                    db.add(
                        StaffSchedule(
                            staff_id=staff.id,
                            date=schedule_date,
                            start_time=WORK_START,
                            end_time=WORK_END,
                        )
                    )
                schedule_count += 1

        await db.commit()

    print(
        f"Maratova Beauty Studio seed complete: tenant_id={tenant.id}, database={tenant.database_name}, "
        f"{len(BUSINESS_INFO)} business info rows, {len(STAFF)} staff, "
        f"{service_count} services, {schedule_count} schedule days."
    )


if __name__ == "__main__":
    asyncio.run(seed())
