from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.base import Base
from app.db.models import broker as _broker  # noqa: F401
from app.db.models import user_profile as _user_profile  # noqa: F401
from app.db.session import engine

logger = logging.getLogger(__name__)


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS agent_decision_logs CASCADE"))
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "ALTER TABLE agent_matches ADD COLUMN IF NOT EXISTS "
                "notebook JSONB DEFAULT '{}'::jsonb"
            )
        )
    logger.info("Database tables ready")
