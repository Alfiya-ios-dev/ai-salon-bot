import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.models import Master, Service

SERVICES = [
    {"name": "Стрижка", "duration_minutes": 60},
    {"name": "Окрашивание", "duration_minutes": 120},
]

WEEKLY_SCHEDULE = {
    "mon": "10:00-19:00",
    "tue": "10:00-19:00",
    "wed": "10:00-19:00",
    "thu": "10:00-19:00",
    "fri": "10:00-19:00",
    "sat": "10:00-17:00",
}

MASTERS = [
    {"name": "Айгуль", "services": ["Стрижка", "Окрашивание"], "schedule": WEEKLY_SCHEDULE},
    {"name": "Гульназ", "services": ["Стрижка", "Окрашивание"], "schedule": WEEKLY_SCHEDULE},
]


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        for service_data in SERVICES:
            existing = await db.scalar(select(Service).where(Service.name == service_data["name"]))
            if existing is None:
                db.add(Service(**service_data))

        for master_data in MASTERS:
            existing = await db.scalar(select(Master).where(Master.name == master_data["name"]))
            if existing is None:
                db.add(Master(**master_data))

        await db.commit()

    print("Seed data inserted (or already present): 2 services, 2 masters.")


if __name__ == "__main__":
    asyncio.run(seed())
