from datetime import date as date_, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Booking, BookingStatus, Master, MasterScheduleException, Service
from app.schemas import AvailableSlotsResponse

router = APIRouter()

# Candidate start times are generated on this grid within a master's working
# hours; no salon-timezone config exists yet, so schedule/booking times are
# all treated as the same naive wall-clock time (stored as UTC).
SLOT_STEP_MINUTES = 30
WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_SERVICE_DURATION_MINUTES = 30


def _parse_schedule_range(hours: str) -> tuple[time, time]:
    start_str, end_str = hours.split("-")
    start_h, start_m = (int(part) for part in start_str.split(":"))
    end_h, end_m = (int(part) for part in end_str.split(":"))
    return time(start_h, start_m), time(end_h, end_m)


@router.get("/available", response_model=AvailableSlotsResponse)
async def get_available_slots(
    service_id: int = Query(...),
    date: date_ = Query(...),
    master_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    service = await db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail=f"Service {service_id} not found")

    master_query = select(Master)
    if master_id is not None:
        master_query = master_query.where(Master.master_id == master_id)
    result = await db.execute(master_query)
    candidate_masters = [
        master for master in result.scalars().all() if service.name in master.services
    ]

    if master_id is not None and not candidate_masters:
        # Distinguish "master doesn't exist" (404) from "master exists but
        # doesn't offer this service" (empty result, not an error).
        if await db.get(Master, master_id) is None:
            raise HTTPException(status_code=404, detail=f"Master {master_id} not found")

    weekday_key = WEEKDAY_KEYS[date.weekday()]
    day_start = datetime.combine(date, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    services_result = await db.execute(select(Service))
    durations_by_name = {s.name: s.duration_minutes for s in services_result.scalars().all()}

    slot_duration = timedelta(minutes=service.duration_minutes)
    step = timedelta(minutes=SLOT_STEP_MINUTES)
    free_times: set[str] = set()

    for master in candidate_masters:
        hours = master.schedule.get(weekday_key)
        if not hours:
            continue

        has_exception = await db.scalar(
            select(MasterScheduleException.id).where(
                MasterScheduleException.master_id == master.master_id,
                MasterScheduleException.date == date,
            )
        )
        if has_exception is not None:
            continue

        work_start, work_end = _parse_schedule_range(hours)
        work_start_dt = datetime.combine(date, work_start, tzinfo=timezone.utc)
        work_end_dt = datetime.combine(date, work_end, tzinfo=timezone.utc)

        bookings_result = await db.execute(
            select(Booking).where(
                Booking.master_id == master.master_id,
                Booking.booking_datetime >= day_start,
                Booking.booking_datetime < day_end,
                Booking.status != BookingStatus.otmenena,
            )
        )
        occupied: list[tuple[datetime, datetime]] = []
        for booking in bookings_result.scalars().all():
            duration = timedelta(
                minutes=durations_by_name.get(booking.service, DEFAULT_SERVICE_DURATION_MINUTES)
            )
            occupied.append((booking.booking_datetime, booking.booking_datetime + duration))

        slot_start = work_start_dt
        while slot_start + slot_duration <= work_end_dt:
            slot_end = slot_start + slot_duration
            overlaps = any(
                slot_start < occ_end and slot_end > occ_start for occ_start, occ_end in occupied
            )
            if not overlaps:
                free_times.add(slot_start.strftime("%H:%M"))
            slot_start += step

    return AvailableSlotsResponse(
        service_id=service_id,
        date=date,
        master_id=master_id,
        available_slots=sorted(free_times),
    )
