"""Optional contact fields; add gender and date of birth.

Revision ID: 0004_profile_identity
Revises: 0003_mail_notifications
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0004_profile_identity"
down_revision: str | None = "0003_mail_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(text("ALTER TABLE user_profiles ALTER COLUMN location DROP NOT NULL"))
    op.execute(text("ALTER TABLE user_profiles ALTER COLUMN mobile_number DROP NOT NULL"))
    op.execute(
        text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS gender VARCHAR(32)")
    )
    op.execute(
        text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS date_of_birth DATE")
    )


def downgrade() -> None:
    op.execute(text("ALTER TABLE user_profiles DROP COLUMN IF EXISTS date_of_birth"))
    op.execute(text("ALTER TABLE user_profiles DROP COLUMN IF EXISTS gender"))
    op.execute(
        text("UPDATE user_profiles SET location = '' WHERE location IS NULL")
    )
    op.execute(
        text("UPDATE user_profiles SET mobile_number = '' WHERE mobile_number IS NULL")
    )
    op.execute(text("ALTER TABLE user_profiles ALTER COLUMN location SET NOT NULL"))
    op.execute(text("ALTER TABLE user_profiles ALTER COLUMN mobile_number SET NOT NULL"))
