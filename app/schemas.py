from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models import BookingStatus


class IncomingMessage(BaseModel):
    text: str
    timestamp: datetime
    message_id: str


class WebhookRequest(BaseModel):
    event_type: str
    channel: str
    client_external_id: str
    message: IncomingMessage


class WebhookAck(BaseModel):
    status: str
    message_id: str


class BookingCreate(BaseModel):
    dialog_id: int
    master_id: int
    client_name: str
    client_phone: str
    service: str
    booking_datetime: datetime


class BookingUpdate(BaseModel):
    status: BookingStatus


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dialog_id: int
    master_id: int
    client_name: str
    client_phone: str
    service: str
    booking_datetime: datetime
    status: BookingStatus
    created_at: datetime


class ServiceCreate(BaseModel):
    name: str
    duration_minutes: int


class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service_id: int
    name: str
    duration_minutes: int


class MasterCreate(BaseModel):
    name: str
    services: list[str] = []
    schedule: dict[str, str] = {}


class MasterUpdate(BaseModel):
    name: str | None = None
    services: list[str] | None = None
    schedule: dict[str, str] | None = None


class MasterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    master_id: int
    name: str
    services: list[str]
    schedule: dict[str, str]


class MasterScheduleExceptionCreate(BaseModel):
    date: date
    reason: str | None = None


class MasterScheduleExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    master_id: int
    date: date
    reason: str | None


class AvailableSlotsResponse(BaseModel):
    service_id: int
    date: date
    master_id: int | None
    available_slots: list[str]
