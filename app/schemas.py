from datetime import datetime

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
    client_name: str
    client_phone: str
    service: str
    booking_datetime: datetime
    status: BookingStatus
    created_at: datetime
