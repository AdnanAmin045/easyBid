"""trigram indexes for project search

Revision ID: 0002
Revises: 0001
"""
from alembic import op
from sqlalchemy import text

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pg_trgm lets ILIKE '%text%' use an index instead of scanning every row. Supabase ships it;
    # on a Postgres build without it, search still works, only without these indexes.
    available = op.get_bind().scalar(text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'"))
    if not available:
        return
    # Supabase keeps extensions in their own schema, which is already on the search path.
    has_schema = op.get_bind().scalar(text("SELECT 1 FROM pg_namespace WHERE nspname = 'extensions'"))
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm" + (" WITH SCHEMA extensions" if has_schema else ""))
    op.create_index(
        "ix_projects_title_trgm", "projects", ["title"], postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}
    )
    op.create_index(
        "ix_projects_description_trgm",
        "projects",
        ["description"],
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_projects_description_trgm")
    op.execute("DROP INDEX IF EXISTS ix_projects_title_trgm")
