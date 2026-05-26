from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.db.session import get_db
from app.core.config import settings

router = APIRouter()


@router.get("/ping")
async def db_ping(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    try:
        await db.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB ping failed: {exc!s}") from exc


def _safe_url_parts(url: URL) -> dict[str, str | int | None]:
    return {
        "drivername": url.drivername,
        "host": url.host,
        "port": url.port,
        "database": url.database,
        "username": url.username,
    }


@router.get("/info")
async def db_info() -> dict[str, object]:
    url = make_url(settings.DATABASE_URL)
    return {"database_url": _safe_url_parts(url)}
