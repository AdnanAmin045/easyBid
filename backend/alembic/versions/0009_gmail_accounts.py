"""More than one Gmail account: a table for them, and which one each campaign, recipient and application used

The single connection that used to live in app_config ('jobs_gmail') becomes the first, default account, and
everything already sent is attributed to it, because its threads live in that mailbox.

Revision ID: 0009
Revises: 0008
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

USERS = ("outreach_campaigns", "outreach_recipients", "job_applications")


def upgrade() -> None:
    op.create_table(
        "gmail_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("sender_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("signature", sa.String(1000), nullable=False, server_default=""),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE gmail_accounts ENABLE ROW LEVEL SECURITY")
    for table in USERS:
        op.add_column(table, sa.Column("gmail_account_id", sa.Integer(), sa.ForeignKey("gmail_accounts.id", ondelete="SET NULL")))

    connection = op.get_bind()
    row = connection.execute(sa.text("SELECT value FROM app_config WHERE key = 'jobs_gmail'")).first()
    old = row[0] if row else None
    if isinstance(old, str):
        old = json.loads(old)
    if old and old.get("email") and old.get("refresh_token"):
        account_id = connection.execute(
            sa.text(
                "INSERT INTO gmail_accounts (email, refresh_token, scopes, is_default) "
                "VALUES (:email, :token, :scopes, true) RETURNING id"
            ),
            {"email": old["email"].lower(), "token": old["refresh_token"], "scopes": old.get("scopes", "")},
        ).scalar_one()
        # Mail that already went out lives in this mailbox. Campaigns keep following the default account.
        connection.execute(sa.text("UPDATE outreach_recipients SET gmail_account_id = :id WHERE gmail_thread_id IS NOT NULL"), {"id": account_id})
        connection.execute(sa.text("UPDATE job_applications SET gmail_account_id = :id WHERE gmail_thread_id IS NOT NULL"), {"id": account_id})
        connection.execute(sa.text("DELETE FROM app_config WHERE key = 'jobs_gmail'"))


def downgrade() -> None:
    for table in USERS:
        op.drop_column(table, "gmail_account_id")
    op.drop_table("gmail_accounts")
