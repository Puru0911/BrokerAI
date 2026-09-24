from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, status
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
)

from app.core.auth import AuthNotConfiguredError, decode_access_token, job_secret_matches
from app.core.config import settings


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None


def _dev_user_from_token(token: str) -> CurrentUser | None:
    if not token.startswith("dev:"):
        return None
    if settings.ENV.strip().lower() != "local":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dev bearer tokens are disabled outside ENV=local",
        )
    email = token.removeprefix("dev:").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dev bearer token",
        )
    return CurrentUser(id=f"dev:{email}", email=email)


async def user_from_access_token(token: str) -> CurrentUser:
    cleaned = token.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    dev_user = _dev_user_from_token(cleaned)
    if dev_user is not None:
        return dev_user

    try:
        payload = await decode_access_token(cleaned)
    except AuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token has expired",
        ) from exc
    except InvalidAudienceError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token audience is invalid",
        ) from exc
    except InvalidIssuerError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token issuer is invalid",
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        ) from exc

    email = payload.get("email")
    return CurrentUser(
        id=str(payload["sub"]),
        email=email if isinstance(email, str) else None,
    )


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return await user_from_access_token(authorization.removeprefix("Bearer ").strip())


async def require_job_secret(
    x_job_secret: str | None = Header(default=None, alias="X-Job-Secret"),
) -> None:
    expected = (settings.INTERNAL_JOB_SECRET or "").strip()
    if len(expected) < 16:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INTERNAL_JOB_SECRET is not configured.",
        )
    if not job_secret_matches(x_job_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid job secret",
        )
