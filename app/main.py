from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.bookings import router as bookings_router
from app.api.masters import router as masters_router
from app.api.services import router as services_router
from app.api.slots import router as slots_router
from app.api.webhook import router as webhook_router
from app.database import Base, engine
from app import models  # noqa: F401  (registers models on Base.metadata)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Beauty Salon Bot Backend", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(bookings_router, prefix="/api/v1/bookings", tags=["Bookings"])
app.include_router(services_router, prefix="/api/v1/services", tags=["Services"])
app.include_router(masters_router, prefix="/api/v1/masters", tags=["Masters"])
app.include_router(slots_router, prefix="/api/v1/slots", tags=["Slots"])
