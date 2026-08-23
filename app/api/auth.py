from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.registry_models import Tenant
from app.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.services.auth_service import create_access_token, hash_password, verify_password
from app.tenant_db import provision_tenant_database

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing_email = await db.scalar(select(Tenant).where(Tenant.email == payload.email))
    if existing_email is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    existing_phone = await db.scalar(
        select(Tenant).where(Tenant.business_phone_number == payload.business_phone_number)
    )
    if existing_phone is not None:
        raise HTTPException(status_code=409, detail="Business phone number already registered")

    # database_name depends on the new row's id, so it's inserted with a
    # placeholder, flushed to get the id, then patched before commit.
    tenant = Tenant(
        business_name=payload.business_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        business_phone_number=payload.business_phone_number,
        database_name="pending",
    )
    db.add(tenant)
    await db.flush()

    tenant.database_name = f"tenant_{tenant.id}_db"

    try:
        await provision_tenant_database(tenant.database_name)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to provision tenant database: {exc}")

    await db.commit()
    await db.refresh(tenant)

    token = create_access_token(tenant.id, tenant.database_name, tenant.email)
    return TokenResponse(access_token=token, tenant_id=tenant.id, business_name=tenant.business_name)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    tenant = await db.scalar(select(Tenant).where(Tenant.email == payload.email))
    if tenant is None or not verify_password(payload.password, tenant.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(tenant.id, tenant.database_name, tenant.email)
    return TokenResponse(access_token=token, tenant_id=tenant.id, business_name=tenant.business_name)
