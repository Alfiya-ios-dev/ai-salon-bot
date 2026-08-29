from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import BookingStatus


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    business_name: str = Field(min_length=1)
    business_phone_number: str = Field(min_length=5, max_length=50)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: int
    business_name: str


class IncomingMessage(BaseModel):
    text: str
    timestamp: datetime
    message_id: str
    # What kind of message this is, as reported by the channel (WhatsApp via
    # n8n). "text" is the only type the bot currently understands — anything
    # else (audio/voice/image/video/document/sticker/...) gets a canned
    # "can't handle this yet" reply in webhook.py instead of going through
    # the AI pipeline.
    message_type: str = "text"


class WebhookRequest(BaseModel):
    # Which business's WhatsApp number the client messaged — webhook.py uses
    # this (not a raw tenant_id) to look up the tenant in the registry and
    # route to that tenant's own database.
    business_phone_number: str
    event_type: str
    channel: str
    client_external_id: str
    message: IncomingMessage


class WebhookAck(BaseModel):
    status: str
    message_id: str
    # Set only for the immediate, synchronous canned reply to unsupported
    # media (see webhook.py) — the normal text pipeline's reply is delivered
    # later, asynchronously, after the debounce window, so this stays None.
    reply: str | None = None


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


class ServiceUpdate(BaseModel):
    category: str | None = None
    name: str | None = None
    price: int | None = None
    duration_minutes: int | None = None
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
    service_ids: list[int] = []


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


class BusinessInfoCreate(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str


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


class DocumentResponse(BaseModel):
    id: int
    filename: str
    created_at: datetime


class StopCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True


class StopCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool


class ManagerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = None
    is_senior: bool = False


class ManagerResponse(BaseModel):
    id: int
    name: str
    phone: str | None
    is_senior: bool
