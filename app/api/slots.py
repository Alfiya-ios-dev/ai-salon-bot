from datetime import date as date_

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_db
from app.models import Service, Staff, StaffService
from app.schemas import AvailableSlotsResponse
from app.services.booking_service import compute_free_slots

router = APIRouter()


@router.get("/available", response_model=AvailableSlotsResponse)
async def get_available_slots(
    service_id: int = Query(...),
    date: date_ = Query(...),
    staff_id: int | None = Query(None),
    db: AsyncSession = Depends(get_current_tenant_db),
):
    service = await db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail=f"Service {service_id} not found")

    staff_query = (
        select(Staff)
        .join(StaffService, StaffService.staff_id == Staff.id)
        .where(StaffService.service_id == service_id, Staff.is_active.is_(True))
    )
    if staff_id is not None:
        staff_query = staff_query.where(Staff.id == staff_id)
    result = await db.execute(staff_query)
    candidate_staff = result.scalars().all()

    if staff_id is not None and not candidate_staff:
        # Distinguish "staff doesn't exist" (404) from "staff exists but
        # doesn't offer this service" (empty result, not an error).
        if await db.get(Staff, staff_id) is None:
            raise HTTPException(status_code=404, detail=f"Staff {staff_id} not found")

    services_result = await db.execute(select(Service))
    durations_by_id = {s.id: s.duration_minutes for s in services_result.scalars().all()}

    free_slots = await compute_free_slots(db, service, date, candidate_staff, durations_by_id)

    return AvailableSlotsResponse(
        service_id=service_id,
        date=date,
        staff_id=staff_id,
        available_slots=sorted({slot.strftime("%H:%M") for slot in free_slots}),
    )
