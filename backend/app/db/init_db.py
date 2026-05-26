from __future__ import annotations

from sqlalchemy import text

from app.db.base import Base
from app.db.models import broker_session as _broker_session  # noqa: F401
from app.db.models import user_profile as _user_profile  # noqa: F401
from app.db.session import engine


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # The MVP still bootstraps schema without migrations. Drop the first RAG
        # draft field now that vector documents are derived by the semantic LLM.
        await connection.execute(
            text("ALTER TABLE broker_requests DROP COLUMN IF EXISTS search_text")
        )
