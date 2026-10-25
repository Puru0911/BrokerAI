"""Background index / screen / evaluate jobs.

Revision ID: 0007_request_jobs
Revises: 0006_suggested_matches
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0007_request_jobs"
down_revision: str | None = "0006_suggested_matches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS agent_request_jobs (
                id VARCHAR(36) PRIMARY KEY,
                request_id VARCHAR(36) NOT NULL REFERENCES agent_requests(id) ON DELETE CASCADE,
                session_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                kind VARCHAR(24) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'queued',
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                trigger_agent BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ DEFAULT now(),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_request_jobs_request_id "
            "ON agent_request_jobs (request_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_request_jobs_session_id "
            "ON agent_request_jobs (session_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_request_jobs_user_id "
            "ON agent_request_jobs (user_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_request_jobs_kind "
            "ON agent_request_jobs (kind)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_request_jobs_status "
            "ON agent_request_jobs (status)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS agent_request_jobs"))
