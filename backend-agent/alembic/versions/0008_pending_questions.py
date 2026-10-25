"""Store clarifying questions on the living brief.

Revision ID: 0008_pending_questions
Revises: 0007_request_jobs
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0008_pending_questions"
down_revision: str | None = "0007_request_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            "ALTER TABLE agent_requests ADD COLUMN IF NOT EXISTS "
            "pending_questions JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
    )


def downgrade() -> None:
    op.execute(text("ALTER TABLE agent_requests DROP COLUMN IF EXISTS pending_questions"))
