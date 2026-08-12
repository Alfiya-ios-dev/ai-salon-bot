from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Master, MasterScheduleException
from app.schemas import (
    MasterCreate,
    MasterResponse,
    MasterScheduleExceptionCreate,
    MasterScheduleExceptionResponse,
    MasterUpdate,
)

router = APIRouter()


@router.post("", response_model=MasterResponse, status_code=201)
async def create_master(payload: MasterCreate, db: AsyncSession = Depends(get_db)):
    master = Master(**payload.model_dump())
    db.add(master)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Master '{payload.name}' already exists")
    await db.refresh(master)
    return master


@router.get("", response_model=list[MasterResponse])
async def list_masters(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Master).order_by(Master.master_id))
    return result.scalars().all()


@router.patch("/{master_id}", response_model=MasterResponse)
async def update_master(master_id: int, payload: MasterUpdate, db: AsyncSession = Depends(get_db)):
    master = await db.get(Master, master_id)
    if master is None:
        raise HTTPException(status_code=404, detail="Master not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(master, field, value)

    await db.commit()
    await db.refresh(master)
    return master


@router.get("/{master_id}/exceptions", response_model=list[MasterScheduleExceptionResponse])
async def list_master_exceptions(master_id: int, db: AsyncSession = Depends(get_db)):
    master = await db.get(Master, master_id)
    if master is None:
        raise HTTPException(status_code=404, detail="Master not found")

    result = await db.execute(
        select(MasterScheduleException)
        .where(MasterScheduleException.master_id == master_id)
        .order_by(MasterScheduleException.date)
    )
    return result.scalars().all()


@router.post(
    "/{master_id}/exceptions", response_model=MasterScheduleExceptionResponse, status_code=201
)
async def create_master_exception(
    master_id: int,
    payload: MasterScheduleExceptionCreate,
    db: AsyncSession = Depends(get_db),
):
    master = await db.get(Master, master_id)
    if master is None:
        raise HTTPException(status_code=404, detail="Master not found")

    exception = MasterScheduleException(master_id=master_id, **payload.model_dump())
    db.add(exception)
    await db.commit()
    await db.refresh(exception)
    return exception


@router.delete("/{master_id}/exceptions/{exception_id}", status_code=204)
async def delete_master_exception(
    master_id: int, exception_id: int, db: AsyncSession = Depends(get_db)
):
    exception = await db.get(MasterScheduleException, exception_id)
    if exception is None or exception.master_id != master_id:
        raise HTTPException(status_code=404, detail="Schedule exception not found")

    await db.delete(exception)
    await db.commit()
