from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import jwt_auth_configured
from app.core.config import settings
from app.db.session import get_db

router = APIRouter()


@router.get("")
async def health() -> dict[str, str]:
    """Liveness probe. Does not touch Postgres or the model provider."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Readiness probe: Postgres is reachable and auth can verify tokens."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    if not settings.is_local and not jwt_auth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="jwt verification is not configured",
        )

    return {"status": "ok", "database": "ok", "auth": "ok"}
