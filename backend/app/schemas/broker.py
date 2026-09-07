from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BrokerSessionCreate(BaseModel):
    initial_message: str | None = Field(default=None, max_length=4000)


class BrokerMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


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

    model_config = {"from_attributes": True}


class BrokerRequestRead(BaseModel):
    id: str
    session_id: str
    user_id: str
    status: str
    request_type: str
    category: str | None
    title: str
    summary: str
    structured_data: dict
    embedding_status: str
    active_graph: str | None
    active_match_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BrokerSessionDetail(BaseModel):
    session: BrokerSessionRead
    messages: list[BrokerMessageRead]
    request: BrokerRequestRead | None = None


class BrokerRequestMatch(BaseModel):
    request_id: str
    title: str
    summary: str
    request_type: str
    category: str | None
    status: str
    distance: float | None


class BrokerMatchRead(BaseModel):
    id: str
    source_request_id: str
    candidate_request_id: str
    status: str
    score: float | None
    rank: int | None
    match_reason: str | None
    mediation_required: bool
    outreach_strategy: str
    last_activity_at: datetime
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BrokerMediationEventRead(BaseModel):
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
