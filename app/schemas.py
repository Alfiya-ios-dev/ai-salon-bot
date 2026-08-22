from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

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
    dialog_id: int | None = None
    staff_id: int
    service_id: int
    client_name: str
    client_phone: str
    booking_datetime: datetime


class BookingUpdate(BaseModel):
    status: BookingStatus


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dialog_id: int | None
    staff_id: int
    service_id: int
    client_name: str
    client_phone: str
    booking_datetime: datetime
    status: BookingStatus
    created_at: datetime


class ServiceCreate(BaseModel):
    category: str | None = None
    name: str
    price: int
    duration_minutes: int
    description: str | None = None


class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str | None
    name: str
    price: int
    duration_minutes: int
    description: str | None


class StaffCreate(BaseModel):
    name: str
    role: str
    is_active: bool = True


class StaffUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class StaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: str
    is_active: bool


class StaffScheduleCreate(BaseModel):
    date: date
    start_time: time
    end_time: time


class StaffScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    staff_id: int
    date: date
    start_time: time
    end_time: time


class BusinessInfoUpsert(BaseModel):
    value: str


class BusinessInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str


class SalesPromptUpdate(BaseModel):
    system_prompt: str = Field(min_length=1)
    upsell_scripts: str = ""
    objection_handling: str = ""


class SalesPromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    system_prompt: str
    upsell_scripts: str
    objection_handling: str
    updated_at: datetime


class AvailableSlotsResponse(BaseModel):
    service_id: int
    date: date
    staff_id: int | None
    available_slots: list[str]
