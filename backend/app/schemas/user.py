from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    location: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=7, max_length=32)


class UserProfileRead(BaseModel):
    id: str
    email: str | None
    name: str
    location: str
    mobile_number: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
