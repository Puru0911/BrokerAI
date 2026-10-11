"""Match lanes: per-pair transcripts and unread state.

Revision ID: 0005_match_lanes
Revises: 0004_profile_identity
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0005_match_lanes"
down_revision: str | None = "0004_profile_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            "ALTER TABLE agent_messages ADD COLUMN IF NOT EXISTS "
            "match_id VARCHAR(36)"
        )
    )
    op.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_agent_messages_match_id'
                ) THEN
                    ALTER TABLE agent_messages
                    ADD CONSTRAINT fk_agent_messages_match_id
                    FOREIGN KEY (match_id) REFERENCES agent_matches(id)
                    ON DELETE SET NULL;
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_messages_match_id "
            "ON agent_messages (match_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_messages_session_match "
            "ON agent_messages (session_id, match_id)"
        )
    )
    op.execute(
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
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_match_reads_match_id "
            "ON agent_match_reads (match_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_match_reads_user_id "
            "ON agent_match_reads (user_id)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS agent_match_reads"))
    op.execute(text("ALTER TABLE agent_messages DROP CONSTRAINT IF EXISTS fk_agent_messages_match_id"))
    op.execute(text("DROP INDEX IF EXISTS ix_agent_messages_session_match"))
    op.execute(text("DROP INDEX IF EXISTS ix_agent_messages_match_id"))
    op.execute(text("ALTER TABLE agent_messages DROP COLUMN IF EXISTS match_id"))
