from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_db
from app.models import BusinessInfo
from app.schemas import BusinessInfoCreate, BusinessInfoResponse, BusinessInfoUpsert

router = APIRouter()


@router.get("", response_model=list[BusinessInfoResponse])
async def list_business_info(db: AsyncSession = Depends(get_current_tenant_db)):
    result = await db.execute(select(BusinessInfo).order_by(BusinessInfo.key))
    return result.scalars().all()


@router.get("/{key}", response_model=BusinessInfoResponse)
async def get_business_info(key: str, db: AsyncSession = Depends(get_current_tenant_db)):
    row = await db.get(BusinessInfo, key)
    if row is None:
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
