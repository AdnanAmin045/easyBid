"""Outreach service: campaigns, recipients, templates and the do-not-contact list

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLES = ("outreach_campaigns", "outreach_recipients", "outreach_templates", "outreach_suppressions")


def upgrade() -> None:
    op.create_table(
        "outreach_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("pause_reason", sa.String(300), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("subject_template", sa.String(300), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("ai_brief", sa.Text(), nullable=False),
        sa.Column("footer", sa.Text(), nullable=False),
        sa.Column("append_signature", sa.Boolean(), nullable=False),
        sa.Column("resume_id", sa.Integer(), sa.ForeignKey("job_resumes.id", ondelete="SET NULL")),
        sa.Column("min_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("max_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("window_start_hour", sa.Integer(), nullable=False),
        sa.Column("window_end_hour", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False),
        sa.Column("weekdays_only", sa.Boolean(), nullable=False),
        sa.Column("ramp_up", sa.Boolean(), nullable=False),
        sa.Column("next_send_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outreach_campaigns_status", "outreach_campaigns", ["status"])
    op.create_index("ix_outreach_campaigns_created_at", "outreach_campaigns", ["created_at"])

    op.create_table(
        "outreach_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("outreach_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("allow_recent", sa.Boolean(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("gmail_message_id", sa.String(100)),
        sa.Column("gmail_thread_id", sa.String(100)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "email"),
    )
    op.create_index("ix_outreach_recipients_queue", "outreach_recipients", ["campaign_id", "status", "position"])
    op.create_index("ix_outreach_recipients_email_sent_at", "outreach_recipients", ["email", "sent_at"])
    op.create_index("ix_outreach_recipients_sent_at", "outreach_recipients", ["sent_at"])

    op.create_table(
        "outreach_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "outreach_suppressions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Same as the other tables: closed to Supabase's public Data API; the backend owns them.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
