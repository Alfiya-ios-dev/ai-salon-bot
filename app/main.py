from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.bookings import router as bookings_router
from app.api.business_info import router as business_info_router
from app.api.prompts import router as prompts_router
from app.api.services import router as services_router
from app.api.slots import router as slots_router
from app.api.staff import router as staff_router
from app.api.webhook import router as webhook_router
from app.database import Base, engine
from app import registry_models  # noqa: F401  (registers Tenant on Base.metadata)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Only the registry DB's own schema (the `tenants` table) is created
    # here. Each tenant's own tables are created individually, in that
    # tenant's own database, at registration time — see
    # app.tenant_db.provision_tenant_database().
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Beauty Salon Bot Backend", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(bookings_router, prefix="/api/v1/bookings", tags=["Bookings"])
app.include_router(services_router, prefix="/api/v1/services", tags=["Services"])
app.include_router(staff_router, prefix="/api/v1/staff", tags=["Staff"])
app.include_router(slots_router, prefix="/api/v1/slots", tags=["Slots"])
app.include_router(prompts_router, prefix="/api/v1/prompts", tags=["Prompts"])
app.include_router(business_info_router, prefix="/api/v1/business-info", tags=["BusinessInfo"])
