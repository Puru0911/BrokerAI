from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.dependencies import require_job_secret
from app.core.config import settings


@pytest.mark.asyncio
async def test_require_job_secret_rejects_missing_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_JOB_SECRET", None)
    with pytest.raises(HTTPException) as exc:
        await require_job_secret(x_job_secret="anything-at-all-16")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_require_job_secret_rejects_wrong_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_JOB_SECRET", "super-secret-job-key")
    with pytest.raises(HTTPException) as exc:
        await require_job_secret(x_job_secret="wrong-secret-job-key")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_job_secret_accepts_matching_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_JOB_SECRET", "super-secret-job-key")
    await require_job_secret(x_job_secret="super-secret-job-key")
