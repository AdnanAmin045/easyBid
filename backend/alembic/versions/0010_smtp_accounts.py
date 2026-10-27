"""Sending accounts that are not Gmail: SMTP to send, IMAP to read the answers

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column("kind", sa.String(10), nullable=False, server_default="gmail"),
    sa.Column("smtp_host", sa.String(255), nullable=False, server_default=""),
    sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="465"),
    sa.Column("smtp_secure", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("smtp_user", sa.String(320), nullable=False, server_default=""),
    sa.Column("smtp_password", sa.Text(), nullable=False, server_default=""),
    sa.Column("imap_host", sa.String(255), nullable=False, server_default=""),
    sa.Column("imap_port", sa.Integer(), nullable=False, server_default="993"),
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("gmail_accounts", column)
    op.alter_column("gmail_accounts", "refresh_token", server_default="")


def downgrade() -> None:
    op.execute("DELETE FROM gmail_accounts WHERE kind = 'smtp'")
    op.alter_column("gmail_accounts", "refresh_token", server_default=None)
    for column in reversed(COLUMNS):
        op.drop_column("gmail_accounts", column.name)
