from datetime import date as date_
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, BookingStatus, Service, Staff, StaffSchedule, StaffService

# No salon-timezone config exists yet, so schedule/booking times are all
# treated as the same naive wall-clock time (stored as UTC) — see app/api/slots.py.
SLOT_STEP_MINUTES = 30


async def compute_free_slots(
    db: AsyncSession,
    service: Service,
    target_date: date_,
    candidate_staff: list[Staff],
    durations_by_id: dict[int, int],
) -> list[datetime]:
    """Core slot-search algorithm, shared by find_available_slots() (name-based,
    used by the AI pipeline) and the /api/v1/slots/available endpoint (id-based).
    """
    day_start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    slot_duration = timedelta(minutes=service.duration_minutes)
    step = timedelta(minutes=SLOT_STEP_MINUTES)
    free_slots: set[datetime] = set()

    for staff in candidate_staff:
        schedule_day = await db.scalar(
            select(StaffSchedule).where(
                StaffSchedule.staff_id == staff.id,
                StaffSchedule.date == target_date,
            )
        )
        if schedule_day is None:
            continue  # no schedule row for this date == not working that day

        work_start_dt = datetime.combine(target_date, schedule_day.start_time, tzinfo=timezone.utc)
        work_end_dt = datetime.combine(target_date, schedule_day.end_time, tzinfo=timezone.utc)

        bookings_result = await db.execute(
            select(Booking).where(
                Booking.staff_id == staff.id,
                Booking.booking_datetime >= day_start,
                Booking.booking_datetime < day_end,
                Booking.status != BookingStatus.otmenena,
            )
        )
        occupied: list[tuple[datetime, datetime]] = []
        for booking in bookings_result.scalars().all():
            duration = timedelta(
                minutes=durations_by_id.get(booking.service_id, service.duration_minutes)
            )
            occupied.append((booking.booking_datetime, booking.booking_datetime + duration))

        slot_start = work_start_dt
        while slot_start + slot_duration <= work_end_dt:
            slot_end = slot_start + slot_duration
            overlaps = any(
                slot_start < occ_end and slot_end > occ_start for occ_start, occ_end in occupied
            )
            if not overlaps:
                free_slots.add(slot_start)
            slot_start += step

    return sorted(free_slots)


async def _durations_by_id(db: AsyncSession) -> dict[int, int]:
    services_result = await db.execute(select(Service))
    return {s.id: s.duration_minutes for s in services_result.scalars().all()}


async def _staff_offering(db: AsyncSession, service_id: int, staff_name: str | None = None) -> list[Staff]:
    query = (
        select(Staff)
        .join(StaffService, StaffService.staff_id == Staff.id)
        .where(StaffService.service_id == service_id, Staff.is_active.is_(True))
    )
    if staff_name is not None:
        query = query.where(Staff.name == staff_name)
    result = await db.execute(query)
    return list(result.scalars().all())


async def find_available_slots(
    db: AsyncSession,
    service_name: str,
    target_date: date_,
    master_name: str | None = None,
) -> list[datetime]:
    """Looks up a service and (optionally) a staff member by name and returns
    the free slots for target_date, taking schedule and existing bookings
    into account.

    Raises ValueError if the service, or an explicitly requested staff
    member, doesn't exist. Returns an empty list (not an error) if that
    staff member exists but doesn't offer this service, or simply has no
    free time that day.
    """
    service = await db.scalar(select(Service).where(Service.name == service_name))
    if service is None:
        raise ValueError(f"Service '{service_name}' not found")

    if master_name is not None:
        exists = await db.scalar(select(Staff.id).where(Staff.name == master_name))
        if exists is None:
            raise ValueError(f"Master '{master_name}' not found")

    candidate_staff = await _staff_offering(db, service.id, master_name)
    durations_by_id = await _durations_by_id(db)

    return await compute_free_slots(db, service, target_date, candidate_staff, durations_by_id)


async def list_available_masters(
    db: AsyncSession,
    service_name: str,
    booking_datetime: datetime,
) -> list[str]:
    """Returns the names of every staff member who offers service_name and
    is actually free at the exact booking_datetime — for "кто из мастеров
    свободен в 14:00?"-style questions, where the client wants real names,
    not just a list of open time slots.

    Raises ValueError if the service doesn't exist. Returns an empty list
    (not an error) if nobody is free right then.
    """
    service = await db.scalar(select(Service).where(Service.name == service_name))
    if service is None:
        raise ValueError(f"Service '{service_name}' not found")

    candidate_staff = await _staff_offering(db, service.id)
    durations_by_id = await _durations_by_id(db)
    target_date = booking_datetime.date()

    available_names = []
    for staff in sorted(candidate_staff, key=lambda s: s.id):
        free_slots = await compute_free_slots(db, service, target_date, [staff], durations_by_id)
        if booking_datetime in free_slots:
            available_names.append(staff.name)
    return available_names


async def _find_first_available_staff(
    db: AsyncSession, service: Service, booking_datetime: datetime, candidate_staff: list[Staff]
) -> Staff | None:
    """Picks the first (lowest id) candidate staff member who is actually
    free at the exact requested booking_datetime, for the master_name=None
    auto-assign path of create_booking().

    Reuses compute_free_slots() (the same day-grid logic find_available_slots
    already relies on) per staff member rather than writing a second overlap
    check, so "free" means exactly the same thing here as in the slots the
    client was shown — and it stays correct if that logic ever changes.
    """
    durations_by_id = await _durations_by_id(db)
    target_date = booking_datetime.date()

    for staff in sorted(candidate_staff, key=lambda s: s.id):
        free_slots = await compute_free_slots(db, service, target_date, [staff], durations_by_id)
        if booking_datetime in free_slots:
            return staff
    return None


async def create_booking(
    db: AsyncSession,
    dialog_id: int,
    service_name: str,
    booking_datetime: datetime,
    client_name: str,
    client_phone: str,
    master_name: str | None = None,
) -> tuple[Booking | None, str | None]:
    """Creates a booking looked up by service/staff *name* (the AI pipeline
    speaks in names, not DB ids). master_name is optional: if the client
    doesn't care who does it, pass None and the first staff member who
    offers service_name and is actually free at booking_datetime gets
    auto-assigned.

    Returns (booking, None) on success, or (None, error_code) on failure, so
    the bot can react and offer an alternative time instead of crashing.
    error_code is one of: "master_not_found", "service_not_found",
    "no_available_master", "slot_taken".
    """
    service = await db.scalar(select(Service).where(Service.name == service_name))
    if service is None:
        print(f"[BOOKING] create_booking failed: service '{service_name}' not found", flush=True)
        return None, "service_not_found"

    if master_name is not None:
        staff = await db.scalar(select(Staff).where(Staff.name == master_name))
        if staff is None:
            print(f"[BOOKING] create_booking failed: master '{master_name}' not found", flush=True)
            return None, "master_not_found"
    else:
        candidate_staff = await _staff_offering(db, service.id)
        staff = await _find_first_available_staff(db, service, booking_datetime, candidate_staff)
        if staff is None:
            print(
                f"[BOOKING] create_booking failed: no available master for "
                f"'{service_name}' at {booking_datetime}",
                flush=True,
            )
            return None, "no_available_master"
        print(f"[BOOKING] Auto-assigned master '{staff.name}' for '{service_name}'", flush=True)

    staff_id = staff.id
    assigned_master_name = staff.name

    booking = Booking(
        dialog_id=dialog_id,
        staff_id=staff_id,
        service_id=service.id,
        client_name=client_name,
        client_phone=client_phone,
        booking_datetime=booking_datetime,
    )
    try:
        # A SAVEPOINT (not a full session rollback) so a conflict only
        # undoes this insert. A plain db.rollback() would expire every
        # object the caller already loaded on this session (e.g. pipeline.py's
        # `dialog`), forcing an implicit lazy-load on next attribute access
        # that async SQLAlchemy can't perform outside an explicit await.
        async with db.begin_nested():
            db.add(booking)
            await db.flush()
    except IntegrityError:
        print(
            f"[BOOKING] create_booking conflict: staff_id={staff_id} "
            f"already booked at {booking_datetime}",
            flush=True,
        )
        return None, "slot_taken"

    await db.commit()
    await db.refresh(booking)
    print(
        f"[BOOKING] Created booking id={booking.id} for master '{assigned_master_name}' at {booking_datetime}",
        flush=True,
    )
    return booking, None


async def cancel_booking(
    db: AsyncSession,
    dialog_id: int,
    booking_id: int | None = None,
) -> tuple[Booking | None, str | None]:
    """Cancels a booking belonging to this dialog.

    If booking_id isn't given, cancels the dialog's most recent non-cancelled
    booking (the common case: a client only has one upcoming appointment and
    doesn't know its internal id). A booking_id belonging to a different
    dialog is treated as not found, so one dialog can't cancel another's
    booking.

    Returns (booking, None) on success, or (None, error_code):
    error_code is one of "booking_not_found", "already_cancelled".
    """
    if booking_id is not None:
        booking = await db.get(Booking, booking_id)
        if booking is not None and booking.dialog_id != dialog_id:
            booking = None
    else:
        booking = await db.scalar(
            select(Booking)
            .where(Booking.dialog_id == dialog_id, Booking.status != BookingStatus.otmenena)
            .order_by(Booking.booking_datetime.desc())
        )

    if booking is None:
        print(f"[BOOKING] cancel_booking failed: no booking found for dialog_id={dialog_id}", flush=True)
        return None, "booking_not_found"

    if booking.status == BookingStatus.otmenena:
        return booking, "already_cancelled"

    booking.status = BookingStatus.otmenena
    await db.commit()
    await db.refresh(booking)
    print(f"[BOOKING] Cancelled booking id={booking.id} for dialog_id={dialog_id}", flush=True)
    return booking, None
