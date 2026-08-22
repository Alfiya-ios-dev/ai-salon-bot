import enum
from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, Time as TimeType, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database import Base
from app.text_utils import sanitize_text


class DialogStatus(str, enum.Enum):
    bot_active = "bot_active"
    escalated = "escalated"
    with_manager = "with_manager"
    bot_resumed = "bot_resumed"
    waiting_followup = "waiting_followup"
    closed = "closed"
    stale = "stale"


class SenderType(str, enum.Enum):
    client = "client"
    bot = "bot"
    manager = "manager"


class BookingStatus(str, enum.Enum):
    novaya = "новая"
    podtverzhdena = "подтверждена"
    otmenena = "отменена"


class PromiseSource(str, enum.Enum):
    auto = "auto"
    manual = "manual"


class Manager(Base):
    __tablename__ = "managers"

    id: Mapped[int] = mapped_column(primary_key=True)
    manager_name: Mapped[str] = mapped_column(String(255))
    notification_phone: Mapped[str | None] = mapped_column(String(50))
    notification_channel: Mapped[str | None] = mapped_column(String(50))
    is_senior: Mapped[bool] = mapped_column(default=False)

    dialogs: Mapped[list["Dialog"]] = relationship(back_populates="assigned_manager")


class Dialog(Base):
    __tablename__ = "dialogs"

    dialog_id: Mapped[int] = mapped_column(primary_key=True)
    client_external_id: Mapped[str] = mapped_column(String(255), index=True)
    channel: Mapped[str] = mapped_column(String(50))
    language: Mapped[str] = mapped_column(String(10))
    status: Mapped[DialogStatus] = mapped_column(default=DialogStatus.bot_active)
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    closed_reason: Mapped[str | None] = mapped_column(Text)
    assigned_manager_id: Mapped[int | None] = mapped_column(ForeignKey("managers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    assigned_manager: Mapped["Manager | None"] = relationship(back_populates="dialogs")
    messages: Mapped[list["Message"]] = relationship(back_populates="dialog")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="dialog")
    summaries: Mapped[list["DialogSummary"]] = relationship(back_populates="dialog")
    promises: Mapped[list["ManagerPromise"]] = relationship(back_populates="dialog")
    followups: Mapped[list["Followup"]] = relationship(back_populates="dialog")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.dialog_id"))
    sender_type: Mapped[SenderType]
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dialog: Mapped["Dialog"] = relationship(back_populates="messages")

    @validates("text")
    def _validate_text(self, key: str, value: str) -> str:
        # Last-resort safety net: sanitizes on every assignment (constructor
        # kwarg or attribute set), so no caller can bypass it — see
        # app/text_utils.py for why this is needed.
        return sanitize_text(value)


class Service(Base):
    """A bookable service offered by the salon. Deliberately generic
    (category/price/description alongside name/duration) so a future admin
    panel can manage the price list without any schema changes."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    price: Mapped[int] = mapped_column()
    duration_minutes: Mapped[int]
    description: Mapped[str | None] = mapped_column(Text)

    staff_links: Mapped[list["StaffService"]] = relationship(back_populates="service")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="service")


class Staff(Base):
    """A staff member (nail master, lash/brow master, or any future role —
    hence the generic `role` string rather than an enum, and `is_active`
    so a future admin panel can retire someone without deleting history)."""

    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)

    service_links: Mapped[list["StaffService"]] = relationship(back_populates="staff")
    schedule_days: Mapped[list["StaffSchedule"]] = relationship(back_populates="staff")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="staff")


class StaffService(Base):
    """Many-to-many: which services a given staff member can perform."""

    __tablename__ = "staff_services"
    __table_args__ = (UniqueConstraint("staff_id", "service_id", name="uq_staff_service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))

    staff: Mapped["Staff"] = relationship(back_populates="service_links")
    service: Mapped["Service"] = relationship(back_populates="staff_links")


class StaffSchedule(Base):
    """A staff member's working hours on one specific calendar date.

    Explicit per-date rows (rather than a repeating weekly template plus a
    separate exceptions table) so a future admin panel can edit any single
    day directly — a day simply having no row here means that staff member
    is off that day, with no separate "exception" concept needed.
    """

    __tablename__ = "staff_schedule"
    __table_args__ = (UniqueConstraint("staff_id", "date", name="uq_staff_schedule_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(TimeType)
    end_time: Mapped[time] = mapped_column(TimeType)

    staff: Mapped["Staff"] = relationship(back_populates="schedule_days")


class BusinessInfo(Base):
    """Generic key/value store for salon-level facts (address, working
    hours, cancellation policy, ...) editable from a future admin panel
    without any schema changes."""

    __tablename__ = "business_info"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("staff_id", "booking_datetime", name="uq_staff_booking_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable: a future admin panel may create walk-in bookings with no
    # chat dialog behind them. All current (bot) booking paths still set it.
    dialog_id: Mapped[int | None] = mapped_column(ForeignKey("dialogs.dialog_id"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    client_name: Mapped[str] = mapped_column(String(255))
    client_phone: Mapped[str] = mapped_column(String(50))
    booking_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(default=BookingStatus.novaya)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dialog: Mapped["Dialog | None"] = relationship(back_populates="bookings")
    staff: Mapped["Staff"] = relationship(back_populates="bookings")
    service: Mapped["Service"] = relationship(back_populates="bookings")


class DialogSummary(Base):
    __tablename__ = "dialog_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.dialog_id"))
    summary_data: Mapped[dict] = mapped_column(JSONB)

    dialog: Mapped["Dialog"] = relationship(back_populates="summaries")


class ManagerPromise(Base):
    __tablename__ = "manager_promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.dialog_id"))
    promise_text: Mapped[str] = mapped_column(Text)
    promise_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[PromiseSource] = mapped_column(default=PromiseSource.auto)

    dialog: Mapped["Dialog"] = relationship(back_populates="promises")


class Followup(Base):
    __tablename__ = "followups"

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.dialog_id"))
    followup_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    dialog: Mapped["Dialog"] = relationship(back_populates="followups")


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SalesPrompt(Base):
    """Admin-editable sales persona/scripts for Main AI, loaded live on every
    reply instead of baked into a static file. Treated as a singleton table
    (callers always take/create the lowest-id row) — there's exactly one
    "current" set of scripts, not a history of versions.

    Deliberately does NOT include the tool-usage/anti-hallucination rules
    that make function calling work reliably (see main_ai_service.py's
    TOOL_INSTRUCTIONS) — those stay fixed in code so an admin edit here
    can't accidentally break booking.
    """

    __tablename__ = "sales_prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    upsell_scripts: Mapped[str] = mapped_column(Text, default="")
    objection_handling: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
