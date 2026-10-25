"""View-filter overlay on requests (not part of the indexed brief).

Revision ID: 0010_view_filters
Revises: 0009_attachment_caption
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0010_view_filters"
down_revision: str | None = "0009_attachment_caption"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            "ALTER TABLE agent_requests ADD COLUMN IF NOT EXISTS "
            "view_filters JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
    )


def downgrade() -> None:
    op.execute(text("ALTER TABLE agent_requests DROP COLUMN IF EXISTS view_filters"))
