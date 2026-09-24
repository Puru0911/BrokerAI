from __future__ import annotations

import ssl
from uuid import uuid4

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings


def normalize_async_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _database_host() -> str:
    return (make_url(normalize_async_db_url(settings.DATABASE_URL)).host or "").lower()


def uses_supabase_postgres() -> bool:
    host = _database_host()
    return "supabase.com" in host or "pooler.supabase" in host


def database_ssl_context() -> ssl.SSLContext | None:
    """TLS for remote Postgres. Default: encrypt, do not fail on pooler chain."""
    if not uses_supabase_postgres():
        return None
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        context = ssl.create_default_context()
    if not settings.DATABASE_SSL_VERIFY:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def connect_args() -> dict:
    args: dict = {
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        "statement_cache_size": 0,
        "timeout": 15,
    }
    ssl_context = database_ssl_context()
    if ssl_context is not None:
        args["ssl"] = ssl_context
    return args


engine: AsyncEngine = create_async_engine(
    normalize_async_db_url(settings.DATABASE_URL),
    connect_args=connect_args(),
    poolclass=NullPool,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
