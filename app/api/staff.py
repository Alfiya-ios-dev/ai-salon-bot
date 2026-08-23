from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_db
from app.models import Service, Staff, StaffSchedule, StaffService
from app.schemas import (
    StaffCreate,
    StaffResponse,
    StaffScheduleCreate,
    StaffScheduleResponse,
    StaffUpdate,
)

router = APIRouter()


@router.post("", response_model=StaffResponse, status_code=201)
async def create_staff(payload: StaffCreate, db: AsyncSession = Depends(get_current_tenant_db)):
    staff = Staff(**payload.model_dump())
    db.add(staff)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Staff '{payload.name}' already exists")
    await db.refresh(staff)
    return staff


@router.get("", response_model=list[StaffResponse])
async def list_staff(db: AsyncSession = Depends(get_current_tenant_db)):
    result = await db.execute(select(Staff).order_by(Staff.id))
    return result.scalars().all()


@router.patch("/{staff_id}", response_model=StaffResponse)
async def update_staff(
    staff_id: int, payload: StaffUpdate, db: AsyncSession = Depends(get_current_tenant_db)
):
    staff = await db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(staff, field, value)

    await db.commit()
    await db.refresh(staff)
    return staff


@router.post("/{staff_id}/services/{service_id}", status_code=201)
async def assign_service_to_staff(
    staff_id: int, service_id: int, db: AsyncSession = Depends(get_current_tenant_db)
):
    staff = await db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff not found")
    service = await db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    link = StaffService(staff_id=staff_id, service_id=service_id)
    db.add(link)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Staff already offers this service")
    return {"staff_id": staff_id, "service_id": service_id}


@router.delete("/{staff_id}/services/{service_id}", status_code=204)
async def unassign_service_from_staff(
    staff_id: int, service_id: int, db: AsyncSession = Depends(get_current_tenant_db)
):
    link = await db.scalar(
        select(StaffService).where(StaffService.staff_id == staff_id, StaffService.service_id == service_id)
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Staff does not offer this service")
    await db.delete(link)
    await db.commit()


@router.get("/{staff_id}/schedule", response_model=list[StaffScheduleResponse])
async def list_staff_schedule(staff_id: int, db: AsyncSession = Depends(get_current_tenant_db)):
    staff = await db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff not found")

    result = await db.execute(
        select(StaffSchedule).where(StaffSchedule.staff_id == staff_id).order_by(StaffSchedule.date)
    )
    return result.scalars().all()


@router.post("/{staff_id}/schedule", response_model=StaffScheduleResponse, status_code=201)
async def create_staff_schedule_day(
    staff_id: int,
    payload: StaffScheduleCreate,
    db: AsyncSession = Depends(get_current_tenant_db),
):
    staff = await db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff not found")

    schedule_day = StaffSchedule(staff_id=staff_id, **payload.model_dump())
    db.add(schedule_day)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Schedule for this staff/date already exists")
    await db.refresh(schedule_day)
    return schedule_day


@router.delete("/{staff_id}/schedule/{schedule_id}", status_code=204)
async def delete_staff_schedule_day(
    staff_id: int, schedule_id: int, db: AsyncSession = Depends(get_current_tenant_db)
):
    schedule_day = await db.get(StaffSchedule, schedule_id)
    if schedule_day is None or schedule_day.staff_id != staff_id:
        raise HTTPException(status_code=404, detail="Schedule day not found")

    await db.delete(schedule_day)
    await db.commit()
