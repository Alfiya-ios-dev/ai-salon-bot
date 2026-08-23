from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_db
from app.models import Booking, BookingStatus, Dialog, Service, Staff
from app.schemas import BookingCreate, BookingResponse, BookingUpdate

router = APIRouter()


@router.post("", response_model=BookingResponse, status_code=201)
async def create_booking(payload: BookingCreate, db: AsyncSession = Depends(get_current_tenant_db)):
    staff_exists = await db.scalar(select(Staff.id).where(Staff.id == payload.staff_id))
    if staff_exists is None:
        raise HTTPException(status_code=404, detail=f"Staff {payload.staff_id} not found")

    service_exists = await db.scalar(select(Service.id).where(Service.id == payload.service_id))
    if service_exists is None:
        raise HTTPException(status_code=404, detail=f"Service {payload.service_id} not found")

    if payload.dialog_id is not None:
        dialog_exists = await db.scalar(
            select(Dialog.dialog_id).where(Dialog.dialog_id == payload.dialog_id)
        )
        if dialog_exists is None:
            raise HTTPException(status_code=404, detail=f"Dialog {payload.dialog_id} not found")

    booking = Booking(**payload.model_dump())
    db.add(booking)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Staff {payload.staff_id} already has a booking at {payload.booking_datetime}",
        )
    await db.refresh(booking)
    return booking


@router.get("", response_model=list[BookingResponse])
async def list_bookings(
    status: BookingStatus | None = None,
    dialog_id: int | None = None,
    staff_id: int | None = None,
    db: AsyncSession = Depends(get_current_tenant_db),
):
    query = select(Booking)
    if status is not None:
        query = query.where(Booking.status == status)
    if dialog_id is not None:
        query = query.where(Booking.dialog_id == dialog_id)
    if staff_id is not None:
        query = query.where(Booking.staff_id == staff_id)
    result = await db.execute(query.order_by(Booking.id))
    return result.scalars().all()


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(booking_id: int, db: AsyncSession = Depends(get_current_tenant_db)):
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.patch("/{booking_id}", response_model=BookingResponse)
async def update_booking(
    booking_id: int, payload: BookingUpdate, db: AsyncSession = Depends(get_current_tenant_db)
):
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    booking.status = payload.status
    await db.commit()
    await db.refresh(booking)
    return booking
