from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AgentPushSubscription

logger = logging.getLogger(__name__)

_LOCAL_ENVS = {"local", "dev", "development"}


def preview_text(content: str, *, has_image: bool, has_file: bool) -> str:
    text = (content or "").strip()
    if text:
        return text if len(text) <= 140 else f"{text[:137]}..."
    if has_image and not has_file:
        return "Sent a photo"
    if has_file and not has_image:
        return "Sent a file"
    if has_image or has_file:
        return "Sent an attachment"
    return "New message"


def _urlsafe_b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_vapid_keys() -> dict[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_numbers = private_key.public_key().public_numbers()
    uncompressed = (
        b"\x04"
        + public_numbers.x.to_bytes(32, "big")
        + public_numbers.y.to_bytes(32, "big")
    )
    return {
        "public_key": _urlsafe_b64(uncompressed),
        "private_key": private_pem,
    }


def load_vapid_keys() -> tuple[str, str] | None:
    public_from_env = (settings.VAPID_PUBLIC_KEY or "").strip()
    private_from_env = (settings.VAPID_PRIVATE_KEY or "").strip()
    if public_from_env and private_from_env:
        return public_from_env, private_from_env

    path = settings.vapid_key_file
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            public_key = payload.get("public_key")
            private_key = payload.get("private_key")
            if isinstance(public_key, str) and isinstance(private_key, str) and public_key and private_key:
                return public_key, private_key
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read VAPID keys from %s: %s", path, exc)

    if not settings.is_local and settings.ENV.lower() not in _LOCAL_ENVS:
        return None

    try:
        keys = generate_vapid_keys()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(keys), encoding="utf-8")
        logger.info("Generated local VAPID keys at %s", path)
        return keys["public_key"], keys["private_key"]
    except Exception:
        logger.exception("Could not generate VAPID keys")
        return None


def vapid_public_key() -> str | None:
    keys = load_vapid_keys()
    return keys[0] if keys else None


async def upsert_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> AgentPushSubscription:
    result = await db.execute(
        select(AgentPushSubscription).where(AgentPushSubscription.endpoint == endpoint)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.user_id = user_id
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = user_agent
        await db.flush()
        return existing

    subscription = AgentPushSubscription(
        user_id=user_id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=user_agent,
    )
    db.add(subscription)
    await db.flush()
    return subscription


async def delete_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    endpoint: str,
) -> None:
    result = await db.execute(
        select(AgentPushSubscription).where(
            AgentPushSubscription.user_id == user_id,
            AgentPushSubscription.endpoint == endpoint,
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is not None:
        await db.delete(subscription)
        await db.flush()


async def notify_user(
    db: AsyncSession,
    user_id: str,
    payload: dict[str, Any],
) -> None:
    keys = load_vapid_keys()
    if keys is None:
        return

    _, private_key = keys
    result = await db.execute(
        select(AgentPushSubscription).where(AgentPushSubscription.user_id == user_id)
    )
    subscriptions = list(result.scalars().all())
    if not subscriptions:
        return

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush is not installed; skipping push notifications")
        return

    stale: list[AgentPushSubscription] = []
    body = json.dumps(payload, ensure_ascii=False, default=str)
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=body,
                vapid_private_key=private_key,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
            )
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410}:
                stale.append(subscription)
            else:
                logger.warning(
                    "push failed user=%s endpoint=%s error=%s",
                    user_id,
                    subscription.endpoint[:48],
                    exc,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "push failed user=%s endpoint=%s error=%s",
                user_id,
                subscription.endpoint[:48],
                exc,
            )

    for subscription in stale:
        await db.delete(subscription)
    if stale:
        await db.flush()
