"""SMTP accounts: an optional separate IMAP login (send through a relay such as Brevo, read replies from the mailbox)

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gmail_accounts", sa.Column("imap_user", sa.String(320), nullable=False, server_default=""))
    op.add_column("gmail_accounts", sa.Column("imap_password", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("gmail_accounts", "imap_password")
    op.drop_column("gmail_accounts", "imap_user")
