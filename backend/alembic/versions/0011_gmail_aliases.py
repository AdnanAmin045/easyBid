"""Send-as addresses: an account that sends through another Gmail account

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gmail_accounts", sa.Column("parent_id", sa.Integer(), sa.ForeignKey("gmail_accounts.id", ondelete="CASCADE")))


def downgrade() -> None:
    op.execute("DELETE FROM gmail_accounts WHERE kind = 'alias'")
    op.drop_column("gmail_accounts", "parent_id")
