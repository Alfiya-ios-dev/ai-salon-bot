"""One-time data load for the Maratova Beauty Studio pilot.

This project has no migration tool (Alembic) yet, and `Base.metadata.create_all()`
only creates tables that don't exist — it can't add/rename columns on ones
that already do. `services` and `bookings` changed shape (normalized FKs,
new columns) and `masters`/`master_schedule_exceptions` are gone entirely
(replaced by `staff`/`staff_schedule`), so those four tables are dropped and
recreated here. Everything in them so far was test data from development
(fake masters/services, zero real bookings) — nothing of business value is
lost. `dialogs`/`messages`/`rag_documents` keep their schema; old test rows
in them are just cleared, not dropped.

Usage:
    python scripts/seed_maratova_beauty.py
"""

import asyncio
import sys
from datetime import date, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.models import (  # noqa: E402
    BusinessInfo,
    Dialog,
    Message,
    RagDocument,
    Service,
    Staff,
    StaffSchedule,
    StaffService,
)

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


async def _drop_incompatible_tables() -> None:
    """Old masters/services/bookings/master_schedule_exceptions tables have
    either gone away or changed columns; create_all() can't alter existing
    tables, so they're dropped and recreated fresh below."""
    async with engine.begin() as conn:
        for table in ("bookings", "master_schedule_exceptions", "masters", "services"):
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))


async def _clear_test_rows(db) -> None:
    """dialogs/messages/rag_documents keep their schema — just clear out
    development test rows for a clean slate on the real pilot client."""
    for model in (Message, Dialog, RagDocument):
        await db.execute(model.__table__.delete())
    await db.commit()


async def seed() -> None:
    await _drop_incompatible_tables()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await _clear_test_rows(db)

        for key, value in BUSINESS_INFO.items():
            db.add(BusinessInfo(key=key, value=value))

        staff_by_name: dict[str, Staff] = {}
        for staff_data in STAFF:
            staff = Staff(**staff_data)
            db.add(staff)
            staff_by_name[staff_data["name"]] = staff

        await db.commit()

        service_count = 0
        for category, services, staff_names in SERVICE_GROUPS:
            for name, price, duration_minutes in services:
                service = Service(
                    category=category, name=name, price=price, duration_minutes=duration_minutes
                )
                db.add(service)
                await db.flush()  # need service.id for the StaffService links below
                service_count += 1

                for staff_name in staff_names:
                    db.add(StaffService(staff_id=staff_by_name[staff_name].id, service_id=service.id))

        await db.commit()

        schedule_count = 0
        for staff in staff_by_name.values():
            for day_offset in range(SCHEDULE_DAYS_AHEAD):
                db.add(
                    StaffSchedule(
                        staff_id=staff.id,
                        date=date.today() + timedelta(days=day_offset),
                        start_time=WORK_START,
                        end_time=WORK_END,
                    )
                )
                schedule_count += 1

        await db.commit()

    print(
        "Maratova Beauty Studio seed complete: "
        f"{len(BUSINESS_INFO)} business info rows, {len(STAFF)} staff, "
        f"{service_count} services, {schedule_count} schedule days."
    )


if __name__ == "__main__":
    asyncio.run(seed())
