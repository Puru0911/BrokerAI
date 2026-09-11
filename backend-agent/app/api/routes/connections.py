from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, get_current_user, user_from_access_token
from app.api.routes.users import get_profile_for_current_user
from app.core.config import settings
from app.db.models import UserProfile
from app.db.session import AsyncSessionLocal, get_db
from app.schemas.broker import (
    ConnectionAttachmentRead,
    ConnectionDetailRead,
    ConnectionMessageCreate,
    ConnectionMessageRead,
    ConnectionSummaryRead,
    PushSubscriptionCreate,
    PushUnsubscribe,
    VapidPublicKeyRead,
)
from app.services.attachments import AttachmentError
from app.services.connections import (
    ConnectionError,
    create_connection_file,
    fanout_connection_message,
    get_connection_attachment_for_viewer,
    get_connection_detail,
    get_owned_connection,
    list_connections_for_user,
    mark_connection_read,
    send_connection_message,
    to_attachment_read,
    to_connection_summary,
    to_message_read,
)
from app.services.push import delete_subscription, upsert_subscription, vapid_public_key
from app.services.realtime import hub
from app.services.storage import StorageNotConfiguredError, get_attachment_store

logger = logging.getLogger(__name__)

router = APIRouter()


async def _require_profile(db: AsyncSession, current_user: CurrentUser) -> UserProfile:
    profile = await get_profile_for_current_user(db, current_user)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Create your user profile before starting a broker request.",
        )
    return profile


def _connection_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, StorageNotConfiguredError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, (AttachmentError, ConnectionError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    allowed = {item.rstrip("/") for item in settings.CORS_ORIGINS}
    return origin.rstrip("/") in allowed


@router.get("/connections", response_model=list[ConnectionSummaryRead])
async def list_connections(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConnectionSummaryRead]:
    profile = await _require_profile(db, current_user)
    return await list_connections_for_user(db, profile.id)


@router.get("/connections/{connection_id}", response_model=ConnectionDetailRead)
async def get_connection(
    connection_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectionDetailRead:
    profile = await _require_profile(db, current_user)
    try:
        connection = await get_owned_connection(db, connection_id, profile.id)
        detail = await get_connection_detail(db, connection, profile.id)
        await mark_connection_read(db, connection=connection, user_id=profile.id)
        await db.commit()
        detail.connection.unread_count = 0
        return detail
    except ConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/connections/{connection_id}/messages",
    response_model=ConnectionMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_connection_message(
    connection_id: str,
    payload: ConnectionMessageCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectionMessageRead:
    profile = await _require_profile(db, current_user)
    try:
        connection = await get_owned_connection(db, connection_id, profile.id)
        message = await send_connection_message(
            db,
            connection=connection,
            sender_id=profile.id,
            content=payload.content,
            attachment_ids=payload.attachment_ids,
        )
        await mark_connection_read(
            db,
            connection=connection,
            user_id=profile.id,
            message_id=message.id,
        )
        serialized = await to_message_read(db, message, profile.id)
        await db.commit()
        await fanout_connection_message(db, connection, message)
        return serialized
    except ConnectionError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    except (AttachmentError, StorageNotConfiguredError) as exc:
        raise _connection_http_error(exc) from exc


@router.post(
    "/connections/{connection_id}/attachments",
    response_model=ConnectionAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_connection_attachment(
    connection_id: str,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectionAttachmentRead:
    profile = await _require_profile(db, current_user)
    try:
        connection = await get_owned_connection(db, connection_id, profile.id)
        data = await file.read()
        attachment = await create_connection_file(
            db,
            connection=connection,
            user_id=profile.id,
            filename=file.filename or "upload",
            content_type=file.content_type,
            data=data,
        )
        await db.commit()
        await db.refresh(attachment)
        return await to_attachment_read(attachment)
    except ConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (AttachmentError, StorageNotConfiguredError) as exc:
        raise _connection_http_error(exc) from exc


@router.post("/connections/{connection_id}/read", response_model=ConnectionSummaryRead)
async def mark_read(
    connection_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectionSummaryRead:
    profile = await _require_profile(db, current_user)
    try:
        connection = await get_owned_connection(db, connection_id, profile.id)
        await mark_connection_read(db, connection=connection, user_id=profile.id)
        await db.commit()
        summary = await to_connection_summary(db, connection, profile.id)
        summary.unread_count = 0
        return summary
    except ConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/connections/attachments/{attachment_id}/content")
async def download_connection_attachment(
    attachment_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    profile = await _require_profile(db, current_user)
    try:
        attachment = await get_connection_attachment_for_viewer(db, attachment_id, profile.id)
    except ConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not attachment.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    try:
        content_url = await get_attachment_store().sign(
            attachment.storage_key,
            expires_in=settings.ATTACHMENT_SIGNED_URL_TTL_SECONDS,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage is not available right now.",
        ) from exc
    return RedirectResponse(content_url)


@router.get("/push/vapid-public-key", response_model=VapidPublicKeyRead)
async def get_vapid_public_key(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VapidPublicKeyRead:
    await _require_profile(db, current_user)
    public_key = vapid_public_key()
    if not public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push notifications are not configured.",
        )
    return VapidPublicKeyRead(public_key=public_key)


@router.post("/push/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe_push(
    payload: PushSubscriptionCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await _require_profile(db, current_user)
    await upsert_subscription(
        db,
        user_id=profile.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys["p256dh"],
        auth=payload.keys["auth"],
        user_agent=payload.user_agent,
    )
    await db.commit()


@router.post("/push/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_push(
    payload: PushUnsubscribe,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await _require_profile(db, current_user)
    await delete_subscription(db, user_id=profile.id, endpoint=payload.endpoint)
    await db.commit()


@router.websocket("/ws")
async def broker_websocket(websocket: WebSocket) -> None:
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=4403)
        return

    token = websocket.query_params.get("access_token")
    authorization = websocket.headers.get("authorization")
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        await websocket.close(code=4401)
        return

    try:
        current_user = user_from_access_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        profile = await get_profile_for_current_user(db, current_user)
        if profile is None:
            await websocket.close(code=4403)
            return
        user_id = profile.id

    await websocket.accept()
    hub.register(user_id, websocket)
    try:
        await websocket.send_json({"type": "hello", "user_id": user_id})
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type") if isinstance(data, dict) else None
            if event_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif event_type == "connection.read":
                connection_id = data.get("connection_id")
                if not isinstance(connection_id, str) or not connection_id:
                    continue
                async with AsyncSessionLocal() as db:
                    try:
                        connection = await get_owned_connection(db, connection_id, user_id)
                        await mark_connection_read(
                            db, connection=connection, user_id=user_id
                        )
                        await db.commit()
                    except ConnectionError:
                        continue
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("websocket closed user=%s", user_id, exc_info=True)
    finally:
        hub.disconnect(user_id, websocket)
