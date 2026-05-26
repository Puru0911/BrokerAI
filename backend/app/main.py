from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db.init_db import init_db


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def on_startup() -> None:
        await init_db()

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.APP_NAME, "status": "ok"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> None:
        return None

    app.include_router(api_router)
    return app


app = create_app()
