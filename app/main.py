import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.auth import router as auth_router
from app.api.bookings import router as bookings_router
from app.api.business_info import router as business_info_router
from app.api.documents import router as documents_router
from app.api.managers import router as managers_router
from app.api.prompts import router as prompts_router
from app.api.services import router as services_router
from app.api.slots import router as slots_router
from app.api.staff import router as staff_router
from app.api.stop_categories import router as stop_categories_router
from app.api.telegram import router as telegram_router
from app.api.tenant_status import router as tenant_status_router
from app.api.webhook import router as webhook_router
from app.config import settings
from app.database import Base, engine
from app.services.telegram_poller import run_telegram_polling_loop
from app import registry_models  # noqa: F401  (registers Tenant on Base.metadata)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Only the registry DB's own schema (the `tenants` table) is created
    # here. Each tenant's own tables are created individually, in that
    # tenant's own database, at registration time — see
    # app.tenant_db.provision_tenant_database().
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Fallback delivery path for Telegram while no HTTPS/domain is set up
    # for a real webhook (see app/services/telegram_poller.py) — safe to
    # leave running even once a webhook exists later, since it's a no-op
    # for any tenant with zero pending updates.
    poller_task = asyncio.create_task(run_telegram_polling_loop())
    try:
        yield
    finally:
        poller_task.cancel()


app = FastAPI(title="Beauty Salon Bot Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Was allow_origins=["*"] ("Allow all CORS origins for dev") — settings.
    # CORS_ORIGINS/cors_origins_list already existed for exactly this but was
    # never actually wired in here. Wildcard + allow_credentials=True is also
    # unsafe: browsers reject credentialed cross-origin requests against a
    # literal "*", so Starlette silently reflects the caller's own Origin
    # back instead — meaning any site's browser JS could already call this
    # API with the user's cookies/Authorization header. Switching to the
    # explicit list before the real admin.dalfy.net deploy.
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(webhook_router)
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(bookings_router, prefix="/api/v1/bookings", tags=["Bookings"])
app.include_router(services_router, prefix="/api/v1/services", tags=["Services"])
app.include_router(staff_router, prefix="/api/v1/staff", tags=["Staff"])
app.include_router(slots_router, prefix="/api/v1/slots", tags=["Slots"])
app.include_router(prompts_router, prefix="/api/v1/prompts", tags=["Prompts"])
app.include_router(business_info_router, prefix="/api/v1/business-info", tags=["BusinessInfo"])
app.include_router(documents_router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(stop_categories_router, prefix="/api/v1/stop-categories", tags=["StopCategories"])
app.include_router(managers_router, prefix="/api/v1/managers", tags=["Managers"])
app.include_router(telegram_router, prefix="/api/v1/telegram/webhook", tags=["Telegram"])
app.include_router(tenant_status_router, prefix="/api/v1/tenant", tags=["Tenant"])
