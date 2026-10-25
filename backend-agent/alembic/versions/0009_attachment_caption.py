"""User-typed upload caption separate from broker file description.

Revision ID: 0009_attachment_caption
Revises: 0008_pending_questions
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0009_attachment_caption"
down_revision: str | None = "0008_pending_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text("ALTER TABLE agent_attachments ADD COLUMN IF NOT EXISTS caption TEXT")
    )
    op.execute(
        text(
            "UPDATE agent_attachments SET caption = description "
            "WHERE caption IS NULL AND description IS NOT NULL "
            "AND btrim(description) <> ''"
        )
    )
    op.execute(
        text(
            "UPDATE agent_attachments SET description = NULL "
            "WHERE caption IS NOT NULL AND description = caption"
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            "UPDATE agent_attachments SET description = caption "
            "WHERE (description IS NULL OR btrim(description) = '') "
            "AND caption IS NOT NULL"
        )
    )
    op.execute(text("ALTER TABLE agent_attachments DROP COLUMN IF EXISTS caption"))
