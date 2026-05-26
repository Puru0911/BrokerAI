from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, status

from app.core.config import settings


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWT must have three segments")

    payload = parts[1]
    padded_payload = payload + "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(padded_payload.encode("utf-8"))
    parsed_payload = json.loads(decoded)

    if not isinstance(parsed_payload, dict):
        raise ValueError("JWT payload must be an object")

    return parsed_payload


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = authorization.removeprefix("Bearer ").strip()

    if settings.ENV == "local" and token.startswith("dev:"):
        email = token.removeprefix("dev:").strip().lower()
        if not email or "@" not in email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid dev bearer token",
            )
        return CurrentUser(id=f"dev:{email}", email=email)

    try:
        payload = _decode_jwt_payload(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        ) from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is missing a subject",
        )

    email = payload.get("email")
    return CurrentUser(id=user_id, email=email if isinstance(email, str) else None)
