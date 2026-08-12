import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


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


class Service(Base):
    __tablename__ = "services"

    service_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    duration_minutes: Mapped[int]


class Master(Base):
    __tablename__ = "masters"

    master_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    services: Mapped[list[str]] = mapped_column(JSONB, default=list)
    schedule: Mapped[dict] = mapped_column(JSONB, default=dict)

    bookings: Mapped[list["Booking"]] = relationship(back_populates="master")
    schedule_exceptions: Mapped[list["MasterScheduleException"]] = relationship(
        back_populates="master"
    )


class MasterScheduleException(Base):
    __tablename__ = "master_schedule_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.master_id"))
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(255))

    master: Mapped["Master"] = relationship(back_populates="schedule_exceptions")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("master_id", "booking_datetime", name="uq_master_booking_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.dialog_id"))
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.master_id"))
    client_name: Mapped[str] = mapped_column(String(255))
    client_phone: Mapped[str] = mapped_column(String(50))
    service: Mapped[str] = mapped_column(String(255))
    booking_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(default=BookingStatus.novaya)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dialog: Mapped["Dialog"] = relationship(back_populates="bookings")
    master: Mapped["Master"] = relationship(back_populates="bookings")


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
