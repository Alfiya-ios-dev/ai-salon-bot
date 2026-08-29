from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_db
from app.models import BusinessInfo
from app.schemas import (
    BusinessInfoCreate,
    BusinessInfoResponse,
    BusinessInfoUpsert,
    TenantSettingsResponse,
    TenantSettingsUpdate,
)
from app.services.tenant_settings_service import TENANT_SETTINGS_DEFAULTS, update_tenant_settings

router = APIRouter()


@router.get("", response_model=list[BusinessInfoResponse])
async def list_business_info(db: AsyncSession = Depends(get_current_tenant_db)):
    result = await db.execute(select(BusinessInfo).order_by(BusinessInfo.key))
    rows = {row.key: row.value for row in result.scalars().all()}
    # Tenant-profile settings (industry_type, staff/service labels) always
    # show up here, even if never explicitly set — unset ones fall back to
    # their beauty-salon default, same as get_tenant_settings().
    for key, default in TENANT_SETTINGS_DEFAULTS.items():
        rows.setdefault(key, default)
    return [BusinessInfoResponse(key=key, value=value) for key, value in sorted(rows.items())]


@router.put("", response_model=TenantSettingsResponse)
async def update_business_settings(
    payload: TenantSettingsUpdate, db: AsyncSession = Depends(get_current_tenant_db)
):
    """Bulk update for the tenant-profile settings (industry_type,
    staff_label_singular/plural, service_label) that let the bot's
    terminology fit non-beauty businesses — see tenant_settings_service.py.
    For arbitrary freeform facts (address, working hours, ...), use
    PUT /{key} instead.
    """
    return await update_tenant_settings(db, payload)


@router.get("/{key}", response_model=BusinessInfoResponse)
async def get_business_info(key: str, db: AsyncSession = Depends(get_current_tenant_db)):
    row = await db.get(BusinessInfo, key)
    if row is None:
        if key in TENANT_SETTINGS_DEFAULTS:
            return BusinessInfoResponse(key=key, value=TENANT_SETTINGS_DEFAULTS[key])
        raise HTTPException(status_code=404, detail=f"BusinessInfo key '{key}' not found")
    return row


@router.post("", response_model=BusinessInfoResponse, status_code=201)
async def create_business_info(
    payload: BusinessInfoCreate, db: AsyncSession = Depends(get_current_tenant_db)
):
    row = BusinessInfo(key=payload.key, value=payload.value)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"BusinessInfo key '{payload.key}' already exists")
    await db.refresh(row)
    return row


@router.put("/{key}", response_model=BusinessInfoResponse)
async def upsert_business_info(
    key: str, payload: BusinessInfoUpsert, db: AsyncSession = Depends(get_current_tenant_db)
):
    """PUT is an upsert (creates the key if it doesn't exist yet) — the
    natural fit for a key/value store where "update the address" and "set
    the address for the first time" are the same operation from an admin
    panel's point of view."""
    row = await db.get(BusinessInfo, key)
    if row is None:
        row = BusinessInfo(key=key, value=payload.value)
        db.add(row)
    else:
        row.value = payload.value
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{key}", status_code=204)
async def delete_business_info(key: str, db: AsyncSession = Depends(get_current_tenant_db)):
    row = await db.get(BusinessInfo, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"BusinessInfo key '{key}' not found")
    await db.delete(row)
    await db.commit()
