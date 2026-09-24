"""Initial agent schema.

Idempotent on databases that already used SQLAlchemy create_all.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from app.db.base import Base
from app.db.models import broker as _broker  # noqa: F401
from app.db.models import user_profile as _user_profile  # noqa: F401

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute(
        text(
            "ALTER TABLE agent_matches ADD COLUMN IF NOT EXISTS "
            "notebook JSONB DEFAULT '{}'::jsonb"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
