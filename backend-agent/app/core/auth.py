from __future__ import annotations

import asyncio
import hmac
import logging
import time
from typing import Any

import httpx
import jwt
from jwt import PyJWK
from jwt.exceptions import InvalidTokenError

from app.core.config import settings

logger = logging.getLogger(__name__)

_JWKS_TTL_SECONDS = 3600.0
_ASYMMETRIC_ALGS = {"ES256", "RS256"}

_jwks_keys: dict[str, Any] = {}
_jwks_fetched_at: float = 0.0
_jwks_lock: asyncio.Lock | None = None


class AuthNotConfiguredError(RuntimeError):
    """Raised when this environment cannot verify access tokens."""


def jwt_auth_configured() -> bool:
    return bool(
        (settings.SUPABASE_JWT_SECRET and settings.SUPABASE_JWT_SECRET.strip())
        or (settings.SUPABASE_URL and settings.SUPABASE_URL.strip())
    )


def job_secret_matches(provided: str | None) -> bool:
    expected = (settings.INTERNAL_JOB_SECRET or "").strip()
    if len(expected) < 16 or not provided:
        return False
    return hmac.compare_digest(provided, expected)


def reset_jwks_cache() -> None:
    global _jwks_keys, _jwks_fetched_at
    _jwks_keys = {}
    _jwks_fetched_at = 0.0


def _jwks_lock_ref() -> asyncio.Lock:
    global _jwks_lock
    if _jwks_lock is None:
        _jwks_lock = asyncio.Lock()
    return _jwks_lock


def jwks_url() -> str | None:
    base = (settings.SUPABASE_URL or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/auth/v1/.well-known/jwks.json"


def _decode_options() -> dict[str, Any]:
    audience = (settings.SUPABASE_JWT_AUDIENCE or "").strip() or None
    issuer = settings.jwt_issuer
    kwargs: dict[str, Any] = {
        "leeway": 30,
        "options": {
            "require": ["sub", "exp"],
            "verify_aud": bool(audience),
            "verify_iss": bool(issuer),
        },
    }
    if audience:
        kwargs["audience"] = audience
    if issuer:
        kwargs["issuer"] = issuer
    return kwargs


def _unverified_header(token: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise InvalidTokenError("Invalid bearer token") from exc
    if not isinstance(header, dict):
        raise InvalidTokenError("Invalid bearer token")
    return header


def _require_subject(payload: dict[str, Any]) -> dict[str, Any]:
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise InvalidTokenError("Bearer token is missing a subject")
    return payload


def _decode_with_key(token: str, key: Any, algorithms: list[str]) -> dict[str, Any]:
    payload = jwt.decode(token, key, algorithms=algorithms, **_decode_options())
    return _require_subject(payload)


async def _refresh_jwks() -> dict[str, Any]:
    global _jwks_keys, _jwks_fetched_at
    url = jwks_url()
    if not url:
        raise AuthNotConfiguredError(
            "SUPABASE_URL is not set; cannot fetch JWT signing keys."
        )
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        body = response.json()
    keys: dict[str, Any] = {}
    for item in body.get("keys") or []:
        if not isinstance(item, dict):
            continue
        kid = item.get("kid")
        if not isinstance(kid, str) or not kid:
            continue
        try:
            keys[kid] = PyJWK.from_dict(item).key
        except Exception:
            logger.warning("Skipping unreadable JWKS key kid=%s", kid, exc_info=True)
    _jwks_keys = keys
    _jwks_fetched_at = time.monotonic()
    logger.info("Loaded %s JWT signing key(s) from JWKS", len(keys))
    return keys


async def _signing_key_for_kid(kid: str) -> Any:
    now = time.monotonic()
    if kid in _jwks_keys and now - _jwks_fetched_at < _JWKS_TTL_SECONDS:
        return _jwks_keys[kid]
    async with _jwks_lock_ref():
        if kid in _jwks_keys and time.monotonic() - _jwks_fetched_at < _JWKS_TTL_SECONDS:
            return _jwks_keys[kid]
        keys = await _refresh_jwks()
    key = keys.get(kid)
    if key is None:
        raise InvalidTokenError("Bearer token signing key was not found")
    return key


async def _load_signing_key(kid: str) -> Any:
    try:
        return await _signing_key_for_kid(kid)
    except httpx.HTTPError as exc:
        raise AuthNotConfiguredError(
            "Could not fetch JWT signing keys from Supabase."
        ) from exc


async def warmup_jwks() -> None:
    if not jwks_url():
        return
    try:
        await _refresh_jwks()
    except Exception:
        logger.warning("JWKS warmup failed; first ES256 login will fetch keys", exc_info=True)


async def decode_access_token(token: str) -> dict[str, Any]:
    """Verify a Supabase access token (HS256 secret or ES256/RS256 JWKS)."""
    if not jwt_auth_configured():
        raise AuthNotConfiguredError(
            "Supabase JWT verification is not configured. "
            "Set SUPABASE_URL (for JWKS / ES256 signing keys) and/or "
            "SUPABASE_JWT_SECRET for legacy HS256 tokens."
        )

    header = _unverified_header(token)
    alg = str(header.get("alg") or "")
    kid = header.get("kid") if isinstance(header.get("kid"), str) else None
    secret = (settings.SUPABASE_JWT_SECRET or "").strip()

    if alg in _ASYMMETRIC_ALGS:
        if not isinstance(kid, str) or not kid:
            raise InvalidTokenError("Bearer token is missing a key id")
        key = await _load_signing_key(kid)
        return _decode_with_key(token, key, algorithms=["ES256", "RS256"])

    if secret:
        return _decode_with_key(token, secret, algorithms=["HS256"])

    if isinstance(kid, str) and kid:
        key = await _load_signing_key(kid)
        return _decode_with_key(token, key, algorithms=["ES256", "RS256", "HS256"])

    raise InvalidTokenError("Bearer token algorithm is not supported")
