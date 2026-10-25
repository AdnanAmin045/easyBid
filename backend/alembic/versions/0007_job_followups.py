"""Follow-ups for job applications

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_applications", sa.Column("followups", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("job_applications", sa.Column("followups_sent", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("job_applications", sa.Column("followup_errors", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("job_applications", sa.Column("followup_note", sa.Text()))
    op.add_column("job_applications", sa.Column("followup_claim_at", sa.DateTime(timezone=True)))
    op.add_column("job_applications", sa.Column("followup_retry_at", sa.DateTime(timezone=True)))
    op.add_column("job_applications", sa.Column("last_contact_at", sa.DateTime(timezone=True)))
    op.add_column("job_applications", sa.Column("sent_subject", sa.String(300), nullable=False, server_default=""))
    op.add_column("job_applications", sa.Column("rfc_id", sa.String(300), nullable=False, server_default=""))
    op.add_column("job_applications", sa.Column("outcome", sa.String(10), nullable=False, server_default=""))
    op.add_column("job_applications", sa.Column("checked_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE job_applications SET last_contact_at = sent_at, sent_subject = subject WHERE sent_at IS NOT NULL")
    op.create_index("ix_job_applications_last_contact_at", "job_applications", ["last_contact_at"])


def downgrade() -> None:
    op.drop_index("ix_job_applications_last_contact_at", "job_applications")
    for column in (
        "checked_at", "outcome", "rfc_id", "sent_subject", "last_contact_at", "followup_retry_at",
        "followup_claim_at", "followup_note", "followup_errors", "followups_sent", "followups",
    ):
        op.drop_column("job_applications", column)
