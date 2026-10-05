"""Jobs service: profile, CVs, prompts and applications

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = ("job_profile_items", "job_resumes", "job_prompts", "job_applications")


def upgrade() -> None:
    op.create_table(
        "job_profile_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "job_resumes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "job_prompts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("note", sa.String(300), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "version"),
    )
    op.create_index("ix_job_prompts_kind", "job_prompts", ["kind"])
    op.create_table(
        "job_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("role", sa.String(200), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("to_email", sa.String(320), nullable=False),
        sa.Column("cc", postgresql.JSONB(), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resume_id", sa.Integer(), sa.ForeignKey("job_resumes.id", ondelete="SET NULL")),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("job_prompts.id", ondelete="SET NULL")),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("gmail_message_id", sa.String(100)),
        sa.Column("gmail_thread_id", sa.String(100)),
        sa.Column("error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_applications_status", "job_applications", ["status"])
    op.create_index("ix_job_applications_sent_at", "job_applications", ["sent_at"])
    op.create_index("ix_job_applications_created_at", "job_applications", ["created_at"])
    op.create_index("ix_job_applications_to_email_sent_at", "job_applications", ["to_email", "sent_at"])

    # Same as the other tables: closed to Supabase's public Data API; the backend owns them.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
