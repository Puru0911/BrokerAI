from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.services.google_profile import normalize_gender


class UserProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    gender: str | None = Field(default=None, max_length=32)
    date_of_birth: date | None = None
    location: str | None = Field(default=None, max_length=160)
    mobile_number: str | None = Field(default=None, max_length=32)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Enter your full name.")
        return cleaned

    @field_validator("gender", "location", "mobile_number", mode="before")
    @classmethod
    def empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("gender")
    @classmethod
    def coerce_gender(cls, value: str | None) -> str | None:
        return normalize_gender(value)


class UserProfileRead(BaseModel):
    id: str
    email: str | None
    name: str
    gender: str | None = None
    date_of_birth: date | None = None
    location: str | None = None
    mobile_number: str | None = None
    notify_email: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserProfilePatch(BaseModel):
    notify_email: bool


class GoogleProfileBootstrap(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    google_access_token: str | None = Field(default=None, max_length=8192)

    @field_validator("name", "google_access_token", mode="before")
    @classmethod
    def empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None
