from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from jwt.exceptions import InvalidTokenError

from app.api.dependencies import user_from_access_token
from app.core.auth import (
    decode_access_token,
    job_secret_matches,
    jwt_auth_configured,
    reset_jwks_cache,
)
from app.core.config import settings

SECRET = "test-jwt-secret-which-is-long-enough-32b"
ISSUER = "https://example.supabase.co/auth/v1"
AUDIENCE = "authenticated"


def _claims(**claims) -> dict:
    return {
        "sub": "user-123",
        "email": "ada@example.com",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        **claims,
    }


def _token(**claims) -> str:
    return jwt.encode(_claims(**claims), SECRET, algorithm="HS256")


def _unsigned_token() -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": "forged-user",
                "email": "forged@example.com",
                "aud": AUDIENCE,
                "iss": ISSUER,
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            }
        ).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.fakesig"


@pytest.fixture
def jwt_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_jwks_cache()
    monkeypatch.setattr(settings, "ENV", "local")
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "SUPABASE_JWT_AUDIENCE", AUDIENCE)
    monkeypatch.setattr(settings, "SUPABASE_JWT_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")


@pytest.mark.asyncio
async def test_local_dev_token_is_accepted(
    jwt_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "local")
    user = await user_from_access_token("dev:ada@example.com")
    assert user.id == "dev:ada@example.com"
    assert user.email == "ada@example.com"


@pytest.mark.asyncio
async def test_dev_token_rejected_outside_local(
    jwt_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    with pytest.raises(HTTPException) as exc:
        await user_from_access_token("dev:ada@example.com")
    assert exc.value.status_code == 401
    assert "disabled" in exc.value.detail


@pytest.mark.asyncio
async def test_unsigned_jwt_is_rejected(jwt_settings: None) -> None:
    with pytest.raises(InvalidTokenError):
        await decode_access_token(_unsigned_token())
    with pytest.raises(HTTPException) as exc:
        await user_from_access_token(_unsigned_token())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_valid_hs256_jwt_is_accepted(jwt_settings: None) -> None:
    user = await user_from_access_token(_token())
    assert user.id == "user-123"
    assert user.email == "ada@example.com"


@pytest.mark.asyncio
async def test_expired_jwt_is_rejected(jwt_settings: None) -> None:
    token = _token(exp=datetime.now(UTC) - timedelta(minutes=5))
    with pytest.raises(HTTPException) as exc:
        await user_from_access_token(token)
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail


@pytest.mark.asyncio
async def test_wrong_audience_is_rejected(jwt_settings: None) -> None:
    token = _token(aud="service_role")
    with pytest.raises(HTTPException) as exc:
        await user_from_access_token(token)
    assert exc.value.status_code == 401
    assert "audience" in exc.value.detail


@pytest.mark.asyncio
async def test_wrong_issuer_is_rejected(jwt_settings: None) -> None:
    token = _token(iss="https://evil.example/auth/v1")
    with pytest.raises(HTTPException) as exc:
        await user_from_access_token(token)
    assert exc.value.status_code == 401
    assert "issuer" in exc.value.detail


@pytest.mark.asyncio
async def test_wrong_signature_is_rejected(jwt_settings: None) -> None:
    token = jwt.encode(
        _claims(),
        "some-other-secret-value-32bytes-min",
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        await user_from_access_token(token)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_es256_token_uses_jwks_not_hs256_secret(
    jwt_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(
        _claims(),
        private_key,
        algorithm="ES256",
        headers={"kid": "kid-1"},
    )

    async def fake_key(kid: str):
        assert kid == "kid-1"
        return private_key.public_key()

    monkeypatch.setattr("app.core.auth._signing_key_for_kid", fake_key)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "must-not-be-used-as-es256-key-32")
    user = await user_from_access_token(token)
    assert user.id == "user-123"
    assert user.email == "ada@example.com"


@pytest.mark.asyncio
async def test_missing_jwt_config_is_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_jwks_cache()
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", None)
    monkeypatch.setattr(settings, "SUPABASE_URL", None)
    assert jwt_auth_configured() is False
    with pytest.raises(HTTPException) as exc:
        await user_from_access_token(_token())
    assert exc.value.status_code == 503


def test_job_secret_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INTERNAL_JOB_SECRET", "super-secret-job-key")
    assert job_secret_matches("super-secret-job-key") is True
    assert job_secret_matches("nope") is False
    assert job_secret_matches(None) is False
    monkeypatch.setattr(settings, "INTERNAL_JOB_SECRET", "short")
    assert job_secret_matches("short") is False


def test_jwt_issuer_falls_back_to_supabase_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUPABASE_JWT_ISSUER", None)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://abcd.supabase.co")
    assert settings.jwt_issuer == "https://abcd.supabase.co/auth/v1"


def test_public_app_url_prefers_explicit_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example.com/")
    assert settings.public_app_url == "https://app.example.com"


def test_production_app_hides_openapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    from app.main import create_app

    app = create_app()
    routes = {getattr(route, "path", None) for route in app.routes}
    assert "/docs" not in routes
    assert "/openapi.json" not in routes
    assert "/redoc" not in routes
