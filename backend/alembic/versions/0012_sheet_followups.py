"""Follow-ups written in the recipient sheet, and when they are sent

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outreach_recipients", sa.Column("followup_bodies", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("outreach_campaigns", sa.Column("sheet_followup_days", postgresql.JSONB(), nullable=False, server_default=sa.text("'[3, 4]'::jsonb")))


def downgrade() -> None:
    op.drop_column("outreach_campaigns", "sheet_followup_days")
    op.drop_column("outreach_recipients", "followup_bodies")
