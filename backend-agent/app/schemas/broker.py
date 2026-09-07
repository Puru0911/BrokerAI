from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class BrokerSessionCreate(BaseModel):
    initial_message: str | None = Field(default=None, max_length=4000)


class BrokerMessageCreate(BaseModel):
    content: str = Field(default="", max_length=4000)
    attachment_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_text_or_attachments(self) -> BrokerMessageCreate:
        if not self.content.strip() and not self.attachment_ids:
            raise ValueError("Send a message or at least one attachment.")
        return self


class BrokerLinkCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    caption: str | None = Field(default=None, max_length=400)
    request_id: str | None = None


class BrokerAttachmentPatch(BaseModel):
    share_class: Literal["public", "personal"] | None = None
    label: str | None = Field(default=None, max_length=160)
    purpose: str | None = Field(default=None, max_length=32)


class BrokerAttachmentGrantCreate(BaseModel):
    match_id: str
    granted: bool = True


class BrokerAttachmentRead(BaseModel):
    id: str
    session_id: str
    kind: str
    share_class: str
    label: str | None
    purpose: str | None
    original_filename: str | None
    content_type: str | None
    size_bytes: int | None
    url: str | None = None
    content_url: str | None = None
    description: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_attachment(
        cls,
        attachment: Any,
        *,
        include_url: bool = False,
        content_url: str | None = None,
    ) -> BrokerAttachmentRead:
        return cls(
            id=attachment.id,
            session_id=attachment.session_id,
            kind=attachment.kind,
            share_class=attachment.share_class,
            label=attachment.label,
            purpose=attachment.purpose,
            original_filename=attachment.original_filename,
            content_type=attachment.content_type,
            size_bytes=attachment.size_bytes,
            url=attachment.url if include_url else None,
            content_url=content_url,
            description=attachment.description,
            status=attachment.status,
            created_at=attachment.created_at,
        )


class BrokerAttachmentRequestRead(BaseModel):
    id: str
    purpose: str
    suggested_share_class: str
    hint: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BrokerSessionRead(BaseModel):
    id: str
    title: str
    status: str
    summary: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BrokerMessageRead(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime
    attachments: list[BrokerAttachmentRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @classmethod
    def from_message(
        cls,
        message: Any,
        attachments: list[BrokerAttachmentRead] | None = None,
    ) -> BrokerMessageRead:
        return cls(
            id=message.id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            attachments=attachments or [],
        )


class BrokerRequestRead(BaseModel):
    id: str
    session_id: str
    user_id: str
    status: str
    title: str
    summary: str
    details: dict
    indexed: bool
    waiting_match_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_request(cls, request) -> BrokerRequestRead:
        return cls(
            id=request.id,
            session_id=request.session_id,
            user_id=request.user_id,
            status=request.status,
            title=request.title,
            summary=request.summary,
            details=_public_details(request.details or {}),
            indexed=request.indexed_at is not None,
            waiting_match_id=request.waiting_match_id,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )


class BrokerSessionDetail(BaseModel):
    session: BrokerSessionRead
    messages: list[BrokerMessageRead]
    request: BrokerRequestRead | None = None
    attachments: list[BrokerAttachmentRead] = Field(default_factory=list)
    pending_upload_requests: list[BrokerAttachmentRequestRead] = Field(default_factory=list)


class BrokerRequestMatch(BaseModel):
    request_id: str
    title: str
    summary: str
    status: str
    distance: float | None


class BrokerMatchRead(BaseModel):
    id: str
    source_request_id: str
    candidate_request_id: str
    status: str
    close_reason: str | None
    score: float | None
    match_reason: str | None
    last_activity_at: datetime
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BrokerEventRead(BaseModel):
    id: str
    match_id: str
    session_id: str | None
    user_id: str | None
    event_type: str
    message_text: str | None
    payload: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BrokerPartyConnectionRead(BaseModel):
    id: str
    match_id: str
    source_user_id: str
    candidate_user_id: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _public_details(details: dict) -> dict:
    return {key: value for key, value in details.items() if key != "semantic"}
