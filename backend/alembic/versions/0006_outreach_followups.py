"""Outreach follow-ups

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outreach_campaigns", sa.Column("followups", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("outreach_recipients", sa.Column("last_contact_at", sa.DateTime(timezone=True)))
    op.add_column("outreach_recipients", sa.Column("followups_sent", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outreach_recipients", sa.Column("followup_errors", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outreach_recipients", sa.Column("sent_subject", sa.String(300), nullable=False, server_default=""))
    op.add_column("outreach_recipients", sa.Column("rfc_id", sa.String(300), nullable=False, server_default=""))
    op.execute("UPDATE outreach_recipients SET last_contact_at = sent_at WHERE sent_at IS NOT NULL")
    op.create_index("ix_outreach_recipients_last_contact_at", "outreach_recipients", ["last_contact_at"])


def downgrade() -> None:
    op.drop_index("ix_outreach_recipients_last_contact_at", "outreach_recipients")
    for column in ("rfc_id", "sent_subject", "followup_errors", "followups_sent", "last_contact_at"):
        op.drop_column("outreach_recipients", column)
    op.drop_column("outreach_campaigns", "followups")
