"""Source-only suggested matches for request-lane Interested/Skip cards.

Revision ID: 0006_suggested_matches
Revises: 0005_match_lanes
Create Date: 2026-04-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0006_suggested_matches"
down_revision: str | None = "0005_match_lanes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
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
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_suggested_matches_request_id "
            "ON agent_suggested_matches (request_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_suggested_matches_candidate_request_id "
            "ON agent_suggested_matches (candidate_request_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_suggested_matches_status "
            "ON agent_suggested_matches (status)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_suggested_matches_card_message_id "
            "ON agent_suggested_matches (card_message_id)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS agent_suggested_matches"))
