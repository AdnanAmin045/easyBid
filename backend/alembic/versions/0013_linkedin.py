"""LinkedIn posting: accounts, settings and the daily posts

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "linkedin_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("author_urn", sa.String(100), nullable=False, server_default=""),
        sa.Column("access_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("expiry_warned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "linkedin_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("logo", sa.LargeBinary()),
        sa.Column("logo_type", sa.String(50), nullable=False, server_default=""),
    )
    op.create_table(
        "linkedin_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target", sa.String(10), nullable=False),
        sa.Column("post_date", sa.Date(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pillar", sa.String(60), nullable=False, server_default=""),
        sa.Column("topic", sa.String(300), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("poster_spec", postgresql.JSONB()),
        sa.Column("poster", sa.LargeBinary()),
        sa.Column("alt_text", sa.String(500), nullable=False, server_default=""),
        sa.Column("signals", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("linkedin_urn", sa.String(100), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("target", "post_date", "slot"),
    )
    op.create_index("ix_linkedin_posts_status", "linkedin_posts", ["status"])
    op.create_index("ix_linkedin_posts_status_scheduled", "linkedin_posts", ["status", "scheduled_for"])


def downgrade() -> None:
    op.drop_table("linkedin_posts")
    op.drop_table("linkedin_config")
    op.drop_table("linkedin_accounts")
