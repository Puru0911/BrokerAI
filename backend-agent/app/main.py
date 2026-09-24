import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.auth import warmup_jwks
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.init_db import init_db

configure_logging()
logger = logging.getLogger(__name__)


def _docs_url(path: str) -> str | None:
    return None if settings.is_production else path


def _warn_production_config() -> None:
    if not settings.is_production:
        return
    localhost_only = settings.CORS_ORIGINS and all(
        "localhost" in origin or "127.0.0.1" in origin for origin in settings.CORS_ORIGINS
    )
    if localhost_only:
        logger.warning("CORS_ORIGINS is still localhost while ENV=%s", settings.ENV)
    if not (settings.SUPABASE_JWT_SECRET or settings.SUPABASE_URL):
        logger.error("SUPABASE_JWT_SECRET or SUPABASE_URL must be set to verify access tokens")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.2.0",
        docs_url=_docs_url("/docs"),
        redoc_url=_docs_url("/redoc"),
        openapi_url=_docs_url("/openapi.json"),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def on_startup() -> None:
        _warn_production_config()
        await init_db()
        await warmup_jwks()
        from app.services.push import load_vapid_keys

        keys = load_vapid_keys()
        if keys:
            logger.info("Web Push VAPID keys ready path=%s", settings.vapid_key_file)
        else:
            logger.warning("Web Push is not configured; notification subscribe will fail")

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.APP_NAME, "status": "ok", "engine": "agent"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> None:
        return None

    app.include_router(api_router)
    return app


app = create_app()
