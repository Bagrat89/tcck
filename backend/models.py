from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ParsedLocation(BaseModel):
    location_name: str
    type: Literal["point", "district", "street"] = "point"
    lat: float = 0.0
    lng: float = 0.0
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class LocationRecord(BaseModel):
    id: int
    message_text: str
    location_name: str
    location_type: str
    lat: float
    lng: float
    confidence: float
    created_at: datetime
    expires_at: datetime
    channel_message_id: Optional[int] = None

    class Config:
        from_attributes = True


class LocationResponse(BaseModel):
    total: int
    locations: list[LocationRecord]
