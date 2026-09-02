from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_id
from app.database import get_db
from app.registry_models import Tenant
from app.schemas import PilotStatusResponse

router = APIRouter()


@router.get("/pilot-status", response_model=PilotStatusResponse)
async def get_pilot_status(
    tenant_id: int = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)
):
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return PilotStatusResponse(
        used_dialogs_count=tenant.used_dialogs_count,
        max_dialogs_limit=tenant.max_dialogs_limit,
        is_pilot_active=tenant.is_pilot_active,
    )
