from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.config import settings
from app.db.base import Base
from app.db.models import broker as _broker  # noqa: F401
from app.db.models import user_profile as _user_profile  # noqa: F401
from app.db.session import engine

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_head_revision() -> str | None:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


async def init_db() -> None:
    """Prepare the database for this process. Never drops tables.

    Local/dev still uses create_all so `uvicorn --reload` works without a migrate
    step. Every other environment refuses to start unless Alembic is at head.
    """
    if settings.is_local:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text(
                    "ALTER TABLE agent_matches ADD COLUMN IF NOT EXISTS "
                    "notebook JSONB DEFAULT '{}'::jsonb"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS "
                    "notify_email BOOLEAN NOT NULL DEFAULT true"
                )
            )
            await connection.execute(
                text("ALTER TABLE user_profiles ALTER COLUMN location DROP NOT NULL")
            )
            await connection.execute(
                text(
                    "ALTER TABLE user_profiles ALTER COLUMN mobile_number DROP NOT NULL"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS "
                    "gender VARCHAR(32)"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS "
                    "date_of_birth DATE"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE agent_messages ADD COLUMN IF NOT EXISTS "
                    "match_id VARCHAR(36)"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_agent_messages_match_id "
                    "ON agent_messages (match_id)"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_agent_messages_session_match "
                    "ON agent_messages (session_id, match_id)"
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS agent_match_reads (
                        id VARCHAR(36) PRIMARY KEY,
                        match_id VARCHAR(36) NOT NULL REFERENCES agent_matches(id) ON DELETE CASCADE,
                        user_id VARCHAR(64) NOT NULL,
                        last_read_at TIMESTAMPTZ DEFAULT now(),
                        last_read_message_id VARCHAR(36),
                        CONSTRAINT uq_agent_match_reads_pair UNIQUE (match_id, user_id)
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS agent_suggested_matches (
                        id VARCHAR(36) PRIMARY KEY,
                        request_id VARCHAR(36) NOT NULL REFERENCES agent_requests(id) ON DELETE CASCADE,
                        candidate_request_id VARCHAR(36) NOT NULL REFERENCES agent_requests(id) ON DELETE CASCADE,
                        status VARCHAR(24) NOT NULL DEFAULT 'ready',
                        evaluation JSONB NOT NULL DEFAULT '{}'::jsonb,
                        card_message_id VARCHAR(36) REFERENCES agent_messages(id) ON DELETE SET NULL,
                        created_at TIMESTAMPTZ DEFAULT now(),
                        updated_at TIMESTAMPTZ DEFAULT now(),
                        CONSTRAINT uq_agent_suggested_matches_pair UNIQUE (request_id, candidate_request_id)
                    )
                    """
                )
            )
        logger.info("Database tables ready (local create_all)")
        return

    async with engine.connect() as connection:

        def current_revision(sync_conn) -> str | None:
            context = MigrationContext.configure(sync_conn)
            return context.get_current_revision()

        current = await connection.run_sync(current_revision)

    head = alembic_head_revision()
    if head is None:
        raise RuntimeError("Alembic has no head revision. Add a migration before starting.")
    if current is None:
        raise RuntimeError(
            "Database has no Alembic revision. Run `uv run alembic upgrade head` before starting."
        )
    if current != head:
        raise RuntimeError(
            f"Database schema is behind (at {current}, need {head}). "
            "Run `uv run alembic upgrade head`."
        )
    logger.info("Database schema current revision=%s", current)
