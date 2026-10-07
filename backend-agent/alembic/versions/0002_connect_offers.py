"""Introduction offers for one-tap go-ahead in broker chat.

Revision ID: 0002_connect_offers
Revises: 0001_initial
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0002_connect_offers"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS agent_connect_offers (
                id VARCHAR(36) PRIMARY KEY,
                match_id VARCHAR(36) NOT NULL REFERENCES agent_matches(id) ON DELETE CASCADE,
                user_id VARCHAR(64) NOT NULL,
                session_id VARCHAR(36) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                prompt VARCHAR(280) NOT NULL DEFAULT 'Ready to be introduced?',
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                message_id VARCHAR(36),
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                CONSTRAINT uq_agent_connect_offers_pair UNIQUE (match_id, user_id)
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_connect_offers_match_id "
            "ON agent_connect_offers (match_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_connect_offers_user_id "
            "ON agent_connect_offers (user_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_connect_offers_session_id "
            "ON agent_connect_offers (session_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_connect_offers_status "
            "ON agent_connect_offers (status)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS agent_connect_offers"))
