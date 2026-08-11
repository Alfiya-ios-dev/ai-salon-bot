from datetime import datetime

from pydantic import BaseModel


class IncomingMessage(BaseModel):
    text: str
    timestamp: datetime
    message_id: str


class WebhookRequest(BaseModel):
    event_type: str
    channel: str
    client_external_id: str
    message: IncomingMessage


class WebhookResponse(BaseModel):
    action: str
    channel: str
    client_external_id: str
    text: str
