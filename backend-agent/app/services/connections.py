from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AgentConnection,
    AgentConnectionAttachment,
    AgentConnectionMessage,
    AgentConnectionReadState,
    AgentMatch,
    AgentRequest,
    UserProfile,
)
from app.schemas.broker import (
    ConnectionAttachmentRead,
    ConnectionDetailRead,
    ConnectionMessageRead,
    ConnectionPeerRead,
    ConnectionSummaryRead,
)
from app.services.attachments import (
    AttachmentError,
    is_image_type,
    normalize_content_type,
    sanitize_filename,
)
from app.services.push import notify_user, preview_text
from app.services.realtime import hub
from app.services.storage import StorageNotConfiguredError, get_attachment_store

logger = logging.getLogger(__name__)

SYSTEM_CONNECTED_TEXT = "You're connected. You can message each other here."
KIND_USER = "user"
KIND_SYSTEM = "system"
KIND_IMAGE = "image"
KIND_FILE = "file"


class ConnectionError(ValueError):
    """User-facing connection chat error."""


def peer_user_id(connection: AgentConnection, viewer_id: str) -> str:
    if connection.source_user_id == viewer_id:
        return connection.candidate_user_id
    if connection.candidate_user_id == viewer_id:
        return connection.source_user_id
    raise ConnectionError("You are not part of this connection.")


def party_user_ids(connection: AgentConnection) -> tuple[str, str]:
    return connection.source_user_id, connection.candidate_user_id


async def get_owned_connection(
    db: AsyncSession,
    connection_id: str,
    viewer_id: str,
) -> AgentConnection:
    connection = await db.get(AgentConnection, connection_id)
    if connection is None or connection.status != "open":
        raise ConnectionError("Connection not found.")
    if viewer_id not in {connection.source_user_id, connection.candidate_user_id}:
        raise ConnectionError("Connection not found.")
    return connection


async def list_connections_for_user(
    db: AsyncSession,
    viewer_id: str,
) -> list[ConnectionSummaryRead]:
    result = await db.execute(
        select(AgentConnection)
        .where(
            AgentConnection.status == "open",
            or_(
                AgentConnection.source_user_id == viewer_id,
                AgentConnection.candidate_user_id == viewer_id,
            ),
        )
        .order_by(AgentConnection.updated_at.desc())
    )
    connections = list(result.scalars().all())
    return [await to_connection_summary(db, connection, viewer_id) for connection in connections]


async def get_connection_detail(
    db: AsyncSession,
    connection: AgentConnection,
    viewer_id: str,
) -> ConnectionDetailRead:
    result = await db.execute(
        select(AgentConnectionMessage)
        .where(AgentConnectionMessage.connection_id == connection.id)
        .order_by(AgentConnectionMessage.created_at, AgentConnectionMessage.id)
    )
    messages = list(result.scalars().all())
    serialized = [await to_message_read(db, message, viewer_id) for message in messages]
    return ConnectionDetailRead(
        connection=await to_connection_summary(
            db,
            connection,
            viewer_id,
            last_message=serialized[-1] if serialized else None,
        ),
        messages=serialized,
    )


async def seed_connection_chat(db: AsyncSession, connection: AgentConnection) -> AgentConnectionMessage | None:
    result = await db.execute(
        select(AgentConnectionMessage.id).where(
            AgentConnectionMessage.connection_id == connection.id,
            AgentConnectionMessage.kind == KIND_SYSTEM,
        )
    )
    if result.scalar_one_or_none() is not None:
        return None
    message = AgentConnectionMessage(
        connection_id=connection.id,
        sender_user_id=None,
        kind=KIND_SYSTEM,
        content=SYSTEM_CONNECTED_TEXT,
    )
    db.add(message)
    await db.flush()
    return message


async def create_connection_file(
    db: AsyncSession,
    *,
    connection: AgentConnection,
    user_id: str,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> AgentConnectionAttachment:
    if not data:
        raise AttachmentError("The file is empty.")
    if len(data) > settings.ATTACHMENT_MAX_BYTES:
        raise AttachmentError("That file is larger than the 10 MB limit.")

    count_result = await db.execute(
        select(func.count())
        .select_from(AgentConnectionAttachment)
        .where(AgentConnectionAttachment.connection_id == connection.id)
    )
    if int(count_result.scalar_one() or 0) >= settings.ATTACHMENT_MAX_PER_CONNECTION:
        raise AttachmentError("This chat already has the maximum number of files.")

    safe_name = sanitize_filename(filename)
    mime = normalize_content_type(content_type, safe_name)
    kind = KIND_IMAGE if is_image_type(mime) else KIND_FILE
    attachment = AgentConnectionAttachment(
        connection_id=connection.id,
        sender_user_id=user_id,
        kind=kind,
        original_filename=safe_name,
        content_type=mime,
        size_bytes=len(data),
    )
    db.add(attachment)
    await db.flush()

    storage_key = f"connections/{connection.id}/{user_id}/{attachment.id}/{safe_name}"
    try:
        await get_attachment_store().put(storage_key, data, mime)
    except StorageNotConfiguredError:
        await db.delete(attachment)
        await db.flush()
        raise
    attachment.storage_key = storage_key
    await db.flush()
    return attachment


async def send_connection_message(
    db: AsyncSession,
    *,
    connection: AgentConnection,
    sender_id: str,
    content: str,
    attachment_ids: list[str],
) -> AgentConnectionMessage:
    text = (content or "").strip()
    attachments = await _load_pending_attachments(
        db,
        connection_id=connection.id,
        sender_id=sender_id,
        attachment_ids=attachment_ids,
    )
    if not text and not attachments:
        raise ConnectionError("Send a message or at least one attachment.")

    message = AgentConnectionMessage(
        connection_id=connection.id,
        sender_user_id=sender_id,
        kind=KIND_USER,
        content=text,
    )
    db.add(message)
    await db.flush()
    for attachment in attachments:
        attachment.message_id = message.id
    connection.updated_at = datetime.now(UTC)
    await db.flush()
    return message


async def mark_connection_read(
    db: AsyncSession,
    *,
    connection: AgentConnection,
    user_id: str,
    message_id: str | None = None,
) -> AgentConnectionReadState:
    result = await db.execute(
        select(AgentConnectionReadState).where(
            AgentConnectionReadState.connection_id == connection.id,
            AgentConnectionReadState.user_id == user_id,
        )
    )
    state = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if state is None:
        state = AgentConnectionReadState(
            connection_id=connection.id,
            user_id=user_id,
            last_read_at=now,
            last_read_message_id=message_id,
        )
        db.add(state)
    else:
        state.last_read_at = now
        if message_id:
            state.last_read_message_id = message_id
    await db.flush()
    return state


async def to_attachment_read(attachment: AgentConnectionAttachment) -> ConnectionAttachmentRead:
    content_url = None
    if attachment.storage_key:
        content_url = f"/broker/connections/attachments/{attachment.id}/content"
    return ConnectionAttachmentRead(
        id=attachment.id,
        connection_id=attachment.connection_id,
        message_id=attachment.message_id,
        kind=attachment.kind,
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        content_url=content_url,
        created_at=attachment.created_at,
    )


async def to_message_read(
    db: AsyncSession,
    message: AgentConnectionMessage,
    viewer_id: str,
) -> ConnectionMessageRead:
    result = await db.execute(
        select(AgentConnectionAttachment)
        .where(AgentConnectionAttachment.message_id == message.id)
        .order_by(AgentConnectionAttachment.created_at)
    )
    attachments = [await to_attachment_read(item) for item in result.scalars().all()]
    return ConnectionMessageRead(
        id=message.id,
        connection_id=message.connection_id,
        sender_user_id=message.sender_user_id,
        kind=message.kind,
        mine=message.sender_user_id == viewer_id,
        content=message.content or "",
        created_at=message.created_at,
        attachments=attachments,
    )


async def to_connection_summary(
    db: AsyncSession,
    connection: AgentConnection,
    viewer_id: str,
    last_message: ConnectionMessageRead | None = None,
) -> ConnectionSummaryRead:
    peer_id = peer_user_id(connection, viewer_id)
    peer_profile = await db.get(UserProfile, peer_id)
    if peer_profile is None:
        peer = ConnectionPeerRead(
            user_id=peer_id,
            name="Matched person",
            location="",
        )
    else:
        peer = ConnectionPeerRead(
            user_id=peer_profile.id,
            name=peer_profile.name,
            location=peer_profile.location,
        )

    match = await db.get(AgentMatch, connection.match_id)
    if match is not None:
        viewer_is_source = connection.source_user_id == viewer_id
        peer_request_id = (
            match.candidate_request_id if viewer_is_source else match.source_request_id
        )
        peer_request = await db.get(AgentRequest, peer_request_id)
        if peer_request is not None:
            peer.request_title = peer_request.title
            peer.request_summary = peer_request.summary

    if last_message is None:
        last_result = await db.execute(
            select(AgentConnectionMessage)
            .where(AgentConnectionMessage.connection_id == connection.id)
            .order_by(
                AgentConnectionMessage.created_at.desc(),
                AgentConnectionMessage.id.desc(),
            )
            .limit(1)
        )
        last_row = last_result.scalar_one_or_none()
        if last_row is not None:
            last_message = await to_message_read(db, last_row, viewer_id)

    unread = await _unread_count(db, connection.id, viewer_id)
    return ConnectionSummaryRead(
        id=connection.id,
        match_id=connection.match_id,
        status=connection.status,
        peer=peer,
        last_message=last_message,
        unread_count=unread,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


async def fanout_connection_created(
    db: AsyncSession,
    connection: AgentConnection,
) -> None:
    for user_id in party_user_ids(connection):
        summary = await to_connection_summary(db, connection, user_id)
        await hub.send_to_user(
            user_id,
            {
                "type": "connection.created",
                "connection": summary.model_dump(mode="json"),
            },
        )


async def fanout_connection_message(
    db: AsyncSession,
    connection: AgentConnection,
    message: AgentConnectionMessage,
) -> None:
    result = await db.execute(
        select(AgentConnectionAttachment).where(
            AgentConnectionAttachment.message_id == message.id
        )
    )
    attachments = list(result.scalars().all())

    has_image = any(item.kind == KIND_IMAGE or is_image_type(item.content_type) for item in attachments)
    has_file = any(not (item.kind == KIND_IMAGE or is_image_type(item.content_type)) for item in attachments)
    body = preview_text(message.content, has_image=has_image, has_file=has_file)

    for user_id in party_user_ids(connection):
        summary = await to_connection_summary(db, connection, user_id)
        serialized = await to_message_read(db, message, user_id)
        await hub.send_to_user(
            user_id,
            {
                "type": "connection.message",
                "connection": summary.model_dump(mode="json"),
                "message": serialized.model_dump(mode="json"),
            },
        )
        if message.kind != KIND_USER or message.sender_user_id == user_id:
            continue
        await notify_user(
            db,
            user_id,
            {
                "title": summary.peer.name,
                "body": body,
                "url": f"/app?chat={connection.id}",
                "connection_id": connection.id,
            },
        )


async def get_connection_attachment_for_viewer(
    db: AsyncSession,
    attachment_id: str,
    viewer_id: str,
) -> AgentConnectionAttachment:
    attachment = await db.get(AgentConnectionAttachment, attachment_id)
    if attachment is None:
        raise ConnectionError("Attachment not found.")
    await get_owned_connection(db, attachment.connection_id, viewer_id)
    return attachment


async def _unread_count(db: AsyncSession, connection_id: str, viewer_id: str) -> int:
    read_result = await db.execute(
        select(AgentConnectionReadState).where(
            AgentConnectionReadState.connection_id == connection_id,
            AgentConnectionReadState.user_id == viewer_id,
        )
    )
    state = read_result.scalar_one_or_none()
    stmt = (
        select(func.count())
        .select_from(AgentConnectionMessage)
        .where(
            AgentConnectionMessage.connection_id == connection_id,
            AgentConnectionMessage.kind == KIND_USER,
            AgentConnectionMessage.sender_user_id != viewer_id,
        )
    )
    if state is not None:
        stmt = stmt.where(AgentConnectionMessage.created_at > state.last_read_at)
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _load_pending_attachments(
    db: AsyncSession,
    *,
    connection_id: str,
    sender_id: str,
    attachment_ids: list[str],
) -> list[AgentConnectionAttachment]:
    if not attachment_ids:
        return []
    unique_ids = list(dict.fromkeys(attachment_ids))
    result = await db.execute(
        select(AgentConnectionAttachment).where(AgentConnectionAttachment.id.in_(unique_ids))
    )
    found = {item.id: item for item in result.scalars().all()}
    attachments: list[AgentConnectionAttachment] = []
    for attachment_id in unique_ids:
        attachment = found.get(attachment_id)
        if (
            attachment is None
            or attachment.connection_id != connection_id
            or attachment.sender_user_id != sender_id
            or attachment.message_id is not None
        ):
            raise ConnectionError("One of those files is not available to send.")
        attachments.append(attachment)
    return attachments
