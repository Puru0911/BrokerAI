"""Transactional mail log and email-notify preference.

Revision ID: 0003_mail_notifications
Revises: 0002_connect_offers
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0003_mail_notifications"
down_revision: str | None = "0002_connect_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS "
            "notify_email BOOLEAN NOT NULL DEFAULT true"
        )
    )
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS agent_mail_log (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                source_id VARCHAR(80) NOT NULL,
                session_id VARCHAR(36),
                resend_id VARCHAR(64),
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                error TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                CONSTRAINT uq_agent_mail_log_kind_source UNIQUE (kind, source_id)
            )
            """
        )
    )
    op.execute(
        text("CREATE INDEX IF NOT EXISTS ix_agent_mail_log_user_id ON agent_mail_log (user_id)")
    )
    op.execute(
        text("CREATE INDEX IF NOT EXISTS ix_agent_mail_log_kind ON agent_mail_log (kind)")
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_mail_log_session_id "
            "ON agent_mail_log (session_id)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS agent_mail_log"))
    op.execute(text("ALTER TABLE user_profiles DROP COLUMN IF EXISTS notify_email"))
