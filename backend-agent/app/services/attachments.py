from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AgentAttachment,
    AgentAttachmentGrant,
    AgentAttachmentRequest,
    AgentAttachmentShare,
    AgentEvent,
    AgentMatch,
    AgentMessage,
    AgentRequest,
)
from app.schemas.broker import (
    BrokerAttachmentRead,
    BrokerAttachmentRequestRead,
    BrokerMessageRead,
)
from app.services.storage import StorageNotConfiguredError, get_attachment_store
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    add_event,
    counterpart_request_id,
    load_pair_requests,
)

logger = logging.getLogger(__name__)

KIND_FILE = "file"
KIND_URL = "url"

SHARE_PENDING = "pending"
SHARE_PUBLIC = "public"
SHARE_PERSONAL = "personal"

STATUS_READY = "ready"
STATUS_DELETED = "deleted"

REQUEST_PENDING = "pending"
REQUEST_FULFILLED = "fulfilled"
REQUEST_CANCELLED = "cancelled"

PURPOSE_VALUES = (
    "resume",
    "listing_photos",
    "portfolio",
    "id_document",
    "personal_photos",
    "other",
)

ALLOWED_CONTENT_TYPES: dict[str, set[str]] = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "image/heic": {".heic", ".heif"},
    "image/heif": {".heic", ".heif"},
    "application/pdf": {".pdf"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
}

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

ATTACHMENT_REQUEST_KIND = "broker_attachment_request"
ATTACHMENT_PERMISSION_KIND = "broker_attachment_permission"
ATTACHMENT_SHARE_KIND = "broker_attachment_share"
CARD_VERSION = 1

SHAREABLE_MATCH_STATUSES = {MATCH_OPEN, MATCH_ACCEPTED, MATCH_CONNECTED}


class AttachmentError(ValueError):
    """User-facing attachment error."""


def sanitize_filename(name: str | None) -> str:
    raw = Path(name or "upload").name.strip() or "upload"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)
    return cleaned[:180] or "upload"


def normalize_content_type(content_type: str | None, filename: str) -> str:
    claimed = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename).suffix.lower()
    if claimed in ALLOWED_CONTENT_TYPES:
        allowed_suffixes = ALLOWED_CONTENT_TYPES[claimed]
        if suffix and suffix not in allowed_suffixes:
            raise AttachmentError("File type does not match the file name.")
        return claimed
    for mime, suffixes in ALLOWED_CONTENT_TYPES.items():
        if suffix in suffixes:
            return mime
    raise AttachmentError("That file type is not supported.")


def is_image_type(content_type: str | None) -> bool:
    return (content_type or "").startswith("image/")


def can_share_directly(share_class: str) -> bool:
    return share_class == SHARE_PUBLIC


def extract_urls(text: str) -> list[str]:
    found: list[str] = []
    for match in URL_RE.findall(text or ""):
        cleaned = match.rstrip(".,);]")
        if cleaned not in found:
            found.append(cleaned)
    return found


def upload_notice(attachments: list[AgentAttachment], caption: str) -> str:
    """User-visible text when files/links are added. The agent classifies from history."""
    if caption.strip():
        return caption.strip()
    names: list[str] = []
    for item in attachments:
        if item.kind == KIND_URL:
            names.append(item.label or item.url or "link")
        else:
            names.append(item.label or item.original_filename or "file")
    if not names:
        return "Uploaded a file."
    if len(names) == 1:
        kind = "link" if attachments[0].kind == KIND_URL else "file"
        return f"Uploaded a {kind}: {names[0]}"
    return "Uploaded files: " + ", ".join(names)


def public_attachment_payload(
    attachment: AgentAttachment,
    *,
    include_url: bool = False,
    content_url: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": attachment.id,
        "kind": attachment.kind,
        "share_class": attachment.share_class,
        "label": attachment.label,
        "purpose": attachment.purpose,
        "original_filename": attachment.original_filename,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "description": attachment.description,
        "status": attachment.status,
        "created_at": attachment.created_at,
    }
    if include_url and attachment.kind == KIND_URL:
        payload["url"] = attachment.url
    else:
        payload["url"] = attachment.url if include_url else None
    payload["content_url"] = content_url
    return payload


async def signed_content_url(attachment: AgentAttachment) -> str | None:
    if attachment.kind != KIND_FILE or not attachment.storage_key:
        return None
    try:
        return await get_attachment_store().sign(
            attachment.storage_key,
            expires_in=settings.ATTACHMENT_SIGNED_URL_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("signed url failed attachment=%s error=%s", attachment.id, exc)
        return None


async def count_session_attachments(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        select(AgentAttachment).where(
            AgentAttachment.session_id == session_id,
            AgentAttachment.status == STATUS_READY,
        )
    )
    return len(list(result.scalars().all()))


async def list_session_attachments(
    db: AsyncSession,
    session_id: str,
) -> list[AgentAttachment]:
    result = await db.execute(
        select(AgentAttachment)
        .where(
            AgentAttachment.session_id == session_id,
            AgentAttachment.status == STATUS_READY,
        )
        .order_by(AgentAttachment.created_at)
    )
    return list(result.scalars().all())


async def list_pending_upload_requests(
    db: AsyncSession,
    session_id: str,
) -> list[AgentAttachmentRequest]:
    result = await db.execute(
        select(AgentAttachmentRequest)
        .where(
            AgentAttachmentRequest.session_id == session_id,
            AgentAttachmentRequest.status == REQUEST_PENDING,
        )
        .order_by(AgentAttachmentRequest.created_at)
    )
    return list(result.scalars().all())


async def get_owned_attachment(
    db: AsyncSession,
    attachment_id: str,
    user_id: str,
) -> AgentAttachment:
    attachment = await db.get(AgentAttachment, attachment_id)
    if attachment is None or attachment.status != STATUS_READY or attachment.user_id != user_id:
        raise AttachmentError("Attachment not found.")
    return attachment


async def viewer_can_access(
    db: AsyncSession,
    attachment: AgentAttachment,
    viewer_user_id: str,
) -> bool:
    if attachment.status != STATUS_READY:
        return False
    if attachment.user_id == viewer_user_id:
        return True
    result = await db.execute(
        select(AgentAttachmentShare).where(AgentAttachmentShare.attachment_id == attachment.id)
    )
    shares = list(result.scalars().all())
    if not shares:
        return False
    for share in shares:
        match = await db.get(AgentMatch, share.match_id)
        if match is None:
            continue
        source, candidate = await load_pair_requests(db, match)
        for request in (source, candidate):
            if request is not None and request.user_id == viewer_user_id:
                return True
    return False


async def create_file_attachment(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    request_id: str | None,
    filename: str,
    content_type: str | None,
    data: bytes,
    caption: str | None = None,
    upload_request_id: str | None = None,
) -> AgentAttachment:
    if len(data) > settings.ATTACHMENT_MAX_BYTES:
        raise AttachmentError("That file is too large.")
    if await count_session_attachments(db, session_id) >= settings.ATTACHMENT_MAX_PER_SESSION:
        raise AttachmentError("This session already has the maximum number of attachments.")
    safe_name = sanitize_filename(filename)
    mime = normalize_content_type(content_type, safe_name)
    attachment_id = str(uuid4())
    storage_key = f"{user_id}/{session_id}/{attachment_id}/{safe_name}"
    try:
        await get_attachment_store().put(storage_key, data, mime)
    except StorageNotConfiguredError:
        raise
    except Exception as exc:
        logger.warning("storage put failed session=%s error=%s", session_id, exc)
        raise StorageNotConfiguredError("Could not store that file.") from exc

    attachment = AgentAttachment(
        id=attachment_id,
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        kind=KIND_FILE,
        share_class=SHARE_PENDING,
        label=safe_name,
        original_filename=safe_name,
        content_type=mime,
        size_bytes=len(data),
        storage_key=storage_key,
        description=(caption or "").strip() or None,
        status=STATUS_READY,
    )
    db.add(attachment)
    await db.flush()
    if upload_request_id:
        await fulfill_upload_request(db, upload_request_id, attachment)
    return attachment


async def create_link_attachment(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    request_id: str | None,
    url: str,
    caption: str | None = None,
    upload_request_id: str | None = None,
) -> AgentAttachment:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AttachmentError("That does not look like a valid link.")
    if await count_session_attachments(db, session_id) >= settings.ATTACHMENT_MAX_PER_SESSION:
        raise AttachmentError("This session already has the maximum number of attachments.")
    host = parsed.netloc.lower()
    attachment = AgentAttachment(
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        kind=KIND_URL,
        share_class=SHARE_PENDING,
        label=host,
        url=url.strip(),
        description=(caption or "").strip() or None,
        status=STATUS_READY,
    )
    db.add(attachment)
    await db.flush()
    if upload_request_id:
        await fulfill_upload_request(db, upload_request_id, attachment)
    return attachment


async def fulfill_upload_request(
    db: AsyncSession,
    request_id: str,
    attachment: AgentAttachment,
) -> None:
    prompt = await db.get(AgentAttachmentRequest, request_id)
    if prompt is None or prompt.session_id != attachment.session_id:
        return
    if prompt.status != REQUEST_PENDING:
        return
    prompt.status = REQUEST_FULFILLED
    prompt.fulfilled_by_attachment_id = attachment.id
    if not attachment.purpose:
        attachment.purpose = prompt.purpose
    if prompt.hint and not attachment.description:
        attachment.description = prompt.hint


async def attach_to_message(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    message: AgentMessage,
    attachment_ids: list[str],
) -> list[AgentAttachment]:
    if not attachment_ids:
        return []
    unique_ids = list(dict.fromkeys(attachment_ids))
    result = await db.execute(
        select(AgentAttachment).where(
            AgentAttachment.id.in_(unique_ids),
            AgentAttachment.session_id == session_id,
            AgentAttachment.user_id == user_id,
            AgentAttachment.status == STATUS_READY,
        )
    )
    found = {item.id: item for item in result.scalars().all()}
    missing = [item_id for item_id in unique_ids if item_id not in found]
    if missing:
        raise AttachmentError("One of those attachments could not be found.")
    linked: list[AgentAttachment] = []
    for item_id in unique_ids:
        item = found[item_id]
        item.message_id = message.id
        linked.append(item)
    await db.flush()
    return linked


async def ingest_urls_from_text(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    request_id: str | None,
    message: AgentMessage,
    text: str,
) -> list[AgentAttachment]:
    created: list[AgentAttachment] = []
    for url in extract_urls(text):
        existing = await db.execute(
            select(AgentAttachment).where(
                AgentAttachment.session_id == session_id,
                AgentAttachment.kind == KIND_URL,
                AgentAttachment.url == url,
                AgentAttachment.status == STATUS_READY,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        item = await create_link_attachment(
            db,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            url=url,
        )
        item.message_id = message.id
        created.append(item)
    await db.flush()
    return created


async def classify_attachment(
    db: AsyncSession,
    attachment: AgentAttachment,
    *,
    share_class: str,
    label: str | None,
    purpose: str | None,
) -> AgentAttachment:
    if share_class not in {SHARE_PUBLIC, SHARE_PERSONAL}:
        raise AttachmentError("share_class must be public or personal.")
    if purpose and purpose not in PURPOSE_VALUES:
        raise AttachmentError("Unknown attachment purpose.")
    attachment.share_class = share_class
    if label and label.strip():
        attachment.label = label.strip()[:160]
    if purpose:
        attachment.purpose = purpose
    await db.flush()
    return attachment


async def get_grant(
    db: AsyncSession,
    attachment_id: str,
    match_id: str,
) -> AgentAttachmentGrant | None:
    result = await db.execute(
        select(AgentAttachmentGrant).where(
            AgentAttachmentGrant.attachment_id == attachment_id,
            AgentAttachmentGrant.match_id == match_id,
        )
    )
    return result.scalar_one_or_none()


async def pending_permission_exists(
    db: AsyncSession,
    *,
    attachment_id: str,
    match_id: str,
) -> bool:
    result = await db.execute(
        select(AgentEvent).where(
            AgentEvent.match_id == match_id,
            AgentEvent.event_type == "share_permission_requested",
        )
    )
    for event in result.scalars().all():
        if (event.payload or {}).get("attachment_id") == attachment_id:
            grant = await get_grant(db, attachment_id, match_id)
            return grant is None
    return False


def parse_structured_card(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    kind = payload.get("kind")
    if kind not in {ATTACHMENT_REQUEST_KIND, ATTACHMENT_PERMISSION_KIND, ATTACHMENT_SHARE_KIND}:
        return None
    if payload.get("version") != CARD_VERSION:
        return None
    return payload


def _card_message(session_id: str, payload: dict[str, Any]) -> AgentMessage:
    return AgentMessage(
        session_id=session_id,
        role="assistant",
        content=json.dumps(payload, ensure_ascii=False),
    )


async def create_upload_request(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    purpose: str,
    suggested_share_class: str,
    hint: str,
) -> tuple[AgentAttachmentRequest, AgentMessage]:
    if purpose not in PURPOSE_VALUES:
        raise AttachmentError("Unknown attachment purpose.")
    if suggested_share_class not in {SHARE_PUBLIC, SHARE_PERSONAL}:
        suggested_share_class = SHARE_PUBLIC
    prompt = AgentAttachmentRequest(
        session_id=session_id,
        user_id=user_id,
        purpose=purpose,
        suggested_share_class=suggested_share_class,
        hint=hint.strip(),
        status=REQUEST_PENDING,
    )
    db.add(prompt)
    await db.flush()
    message = _card_message(
        session_id,
        {
            "kind": ATTACHMENT_REQUEST_KIND,
            "version": CARD_VERSION,
            "request_id": prompt.id,
            "purpose": purpose,
            "suggested_share_class": suggested_share_class,
            "hint": hint.strip(),
            "title": _purpose_title(purpose),
        },
    )
    db.add(message)
    await db.flush()
    return prompt, message


def _purpose_title(purpose: str) -> str:
    return {
        "resume": "Resume",
        "listing_photos": "Listing photos",
        "portfolio": "Portfolio",
        "id_document": "ID document",
        "personal_photos": "Personal photos",
        "other": "File",
    }.get(purpose, "File")


async def request_share_permission(
    db: AsyncSession,
    *,
    session_id: str,
    match: AgentMatch,
    attachment: AgentAttachment,
    user_id: str,
) -> AgentMessage:
    message = _card_message(
        session_id,
        {
            "kind": ATTACHMENT_PERMISSION_KIND,
            "version": CARD_VERSION,
            "match_id": match.id,
            "attachment_id": attachment.id,
            "label": attachment.label or attachment.original_filename or "this file",
            "purpose": attachment.purpose,
            "reason": "This looks personal. I need your OK before I share it.",
        },
    )
    db.add(message)
    await db.flush()
    await add_event(
        db,
        match_id=match.id,
        event_type="share_permission_requested",
        session_id=session_id,
        user_id=user_id,
        payload={"attachment_id": attachment.id, "message_id": message.id},
    )
    return message


async def record_grant(
    db: AsyncSession,
    *,
    attachment: AgentAttachment,
    match: AgentMatch,
    user_id: str,
    granted: bool,
    source: str,
) -> AgentAttachmentGrant:
    if attachment.user_id != user_id:
        raise AttachmentError("Only the owner can grant sharing.")
    existing = await get_grant(db, attachment.id, match.id)
    status = "granted" if granted else "denied"
    if existing is None:
        existing = AgentAttachmentGrant(
            attachment_id=attachment.id,
            match_id=match.id,
            user_id=user_id,
            status=status,
            source=source,
        )
        db.add(existing)
    else:
        existing.status = status
        existing.source = source
    await db.flush()
    await add_event(
        db,
        match_id=match.id,
        event_type="share_granted" if granted else "share_denied",
        session_id=attachment.session_id,
        user_id=user_id,
        payload={"attachment_id": attachment.id, "source": source},
    )
    return existing


async def share_attachment_to_match(
    db: AsyncSession,
    *,
    match: AgentMatch,
    attachment: AgentAttachment,
    from_request: AgentRequest,
) -> tuple[AgentAttachmentShare | None, AgentMessage | None, str]:
    """Share if allowed. Returns (share, other-party message, status)."""
    if match.status not in SHAREABLE_MATCH_STATUSES:
        return None, None, "match_closed"
    if attachment.status != STATUS_READY:
        return None, None, "missing"

    existing_share_result = await db.execute(
        select(AgentAttachmentShare).where(
            AgentAttachmentShare.attachment_id == attachment.id,
            AgentAttachmentShare.match_id == match.id,
        )
    )
    existing_share = existing_share_result.scalar_one_or_none()
    if existing_share is not None:
        return existing_share, None, "already_shared"

    grant = await get_grant(db, attachment.id, match.id)
    if not can_share_directly(attachment.share_class) and (
        grant is None or grant.status != "granted"
    ):
        return None, None, "needs_permission"

    source, candidate = await load_pair_requests(db, match)
    if source is None or candidate is None:
        return None, None, "missing"
    other_id = counterpart_request_id(match, from_request)
    other = candidate if other_id == candidate.id else source

    include_url = attachment.kind == KIND_URL and attachment.share_class == SHARE_PUBLIC
    card = {
        "kind": ATTACHMENT_SHARE_KIND,
        "version": CARD_VERSION,
        "match_id": match.id,
        "title": attachment.label or attachment.original_filename or "Shared file",
        "attachments": [
            {
                "id": attachment.id,
                "kind": attachment.kind,
                "label": attachment.label,
                "purpose": attachment.purpose,
                "content_type": attachment.content_type,
                "original_filename": attachment.original_filename,
                "url": attachment.url if include_url else None,
            }
        ],
    }
    message = _card_message(other.session_id, card)
    db.add(message)
    await db.flush()
    share = AgentAttachmentShare(
        attachment_id=attachment.id,
        match_id=match.id,
        from_user_id=attachment.user_id,
        to_request_id=other.id,
        shared_message_id=message.id,
    )
    db.add(share)
    await db.flush()
    await add_event(
        db,
        match_id=match.id,
        event_type="attachment_shared",
        session_id=from_request.session_id,
        user_id=attachment.user_id,
        payload={"attachment_id": attachment.id, "to_session_id": other.session_id},
    )
    return share, message, "shared"


async def delete_attachment(db: AsyncSession, attachment: AgentAttachment) -> None:
    if attachment.storage_key:
        try:
            await get_attachment_store().delete(attachment.storage_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("storage delete failed attachment=%s error=%s", attachment.id, exc)
    attachment.status = STATUS_DELETED
    await db.flush()


async def delete_session_files(db: AsyncSession, session_id: str) -> None:
    result = await db.execute(
        select(AgentAttachment).where(AgentAttachment.session_id == session_id)
    )
    for attachment in result.scalars().all():
        if attachment.storage_key and attachment.status != STATUS_DELETED:
            try:
                await get_attachment_store().delete(attachment.storage_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "storage delete failed session=%s attachment=%s error=%s",
                    session_id,
                    attachment.id,
                    exc,
                )


async def attachments_for_messages(
    db: AsyncSession,
    messages: list[AgentMessage],
    *,
    viewer_user_id: str,
) -> dict[str, list[AgentAttachment]]:
    if not messages:
        return {}
    message_ids = [message.id for message in messages]
    result = await db.execute(
        select(AgentAttachment).where(
            AgentAttachment.status == STATUS_READY,
            AgentAttachment.message_id.in_(message_ids),
        )
    )
    by_message: dict[str, list[AgentAttachment]] = {message_id: [] for message_id in message_ids}
    for attachment in result.scalars().all():
        if attachment.message_id and await viewer_can_access(db, attachment, viewer_user_id):
            by_message.setdefault(attachment.message_id, []).append(attachment)

    share_result = await db.execute(
        select(AgentAttachmentShare).where(AgentAttachmentShare.shared_message_id.in_(message_ids))
    )
    for share in share_result.scalars().all():
        attachment = await db.get(AgentAttachment, share.attachment_id)
        if attachment is None or attachment.status != STATUS_READY:
            continue
        if share.shared_message_id and await viewer_can_access(db, attachment, viewer_user_id):
            bucket = by_message.setdefault(share.shared_message_id, [])
            if all(item.id != attachment.id for item in bucket):
                bucket.append(attachment)
    return by_message


async def shared_attachment_ids_for_match(
    db: AsyncSession,
    match_id: str,
) -> set[str]:
    result = await db.execute(
        select(AgentAttachmentShare.attachment_id).where(AgentAttachmentShare.match_id == match_id)
    )
    return {row[0] for row in result.all()}


async def to_attachment_read(
    attachment: AgentAttachment,
    *,
    include_secrets: bool,
) -> BrokerAttachmentRead:
    content_url = None
    if include_secrets and attachment.kind == KIND_FILE:
        content_url = await signed_content_url(attachment)
    return BrokerAttachmentRead.from_attachment(
        attachment,
        include_url=include_secrets and attachment.kind == KIND_URL,
        content_url=content_url,
    )


async def serialize_messages(
    db: AsyncSession,
    messages: list[AgentMessage],
    *,
    viewer_user_id: str,
) -> list[BrokerMessageRead]:
    grouped = await attachments_for_messages(db, messages, viewer_user_id=viewer_user_id)
    serialized: list[BrokerMessageRead] = []
    for message in messages:
        items = grouped.get(message.id) or []
        reads: list[BrokerAttachmentRead] = []
        for attachment in items:
            allowed = await viewer_can_access(db, attachment, viewer_user_id)
            reads.append(await to_attachment_read(attachment, include_secrets=allowed))
        serialized.append(BrokerMessageRead.from_message(message, reads))
    return serialized


async def serialize_session_attachments(
    db: AsyncSession,
    session_id: str,
    *,
    viewer_user_id: str,
) -> list[BrokerAttachmentRead]:
    items = await list_session_attachments(db, session_id)
    reads: list[BrokerAttachmentRead] = []
    for attachment in items:
        allowed = await viewer_can_access(db, attachment, viewer_user_id)
        if not allowed:
            continue
        reads.append(await to_attachment_read(attachment, include_secrets=allowed))
    return reads


def serialize_upload_requests(
    prompts: list[AgentAttachmentRequest],
) -> list[BrokerAttachmentRequestRead]:
    return [BrokerAttachmentRequestRead.model_validate(item) for item in prompts]


async def context_attachments(
    db: AsyncSession,
    *,
    session_id: str,
    new_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items = await list_session_attachments(db, session_id)
    new_set = set(new_ids or [])
    listings: list[dict[str, Any]] = []
    new_uploads: list[dict[str, Any]] = []
    for item in items:
        payload = {
            "id": item.id,
            "kind": item.kind,
            "share_class": item.share_class,
            "label": item.label,
            "purpose": item.purpose,
            "filename": item.original_filename,
            "content_type": item.content_type,
            "description": item.description,
        }
        if item.kind == KIND_URL:
            payload["url"] = item.url
        listings.append(payload)
    new_uploads = [item for item in listings if item["id"] in new_set]
    return listings, new_uploads
