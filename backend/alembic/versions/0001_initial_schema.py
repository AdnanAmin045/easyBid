"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-09-30 12:10:17.173245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = ('alembic_version', 'app_config', 'event_logs', 'profile_items', 'projects', 'prompts', 'proposals')


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('app_config',
    sa.Column('key', sa.String(length=50), nullable=False),
    sa.Column('value', postgresql.JSONB(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('event_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('event', sa.String(length=50), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_event_logs_created_at'), 'event_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_event_logs_event'), 'event_logs', ['event'], unique=False)
    op.create_table('profile_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('projects',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('usd_rate', sa.Float(), nullable=False),
    sa.Column('budget_min', sa.Float(), nullable=True),
    sa.Column('budget_max', sa.Float(), nullable=True),
    sa.Column('weekly_hours', sa.Integer(), nullable=True),
    sa.Column('bid_count', sa.Integer(), nullable=False),
    sa.Column('bid_avg', sa.Float(), nullable=True),
    sa.Column('skills', postgresql.JSONB(), nullable=False),
    sa.Column('skill_ids', postgresql.JSONB(), nullable=False),
    sa.Column('language', sa.String(length=10), nullable=True),
    sa.Column('upgrades', postgresql.JSONB(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_projects_created_at'), 'projects', ['created_at'], unique=False)
    op.create_index(op.f('ix_projects_status'), 'projects', ['status'], unique=False)
    op.create_table('prompts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'version')
    )
    op.create_index(op.f('ix_prompts_kind'), 'prompts', ['kind'], unique=False)
    op.create_table('proposals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('prompt_id', sa.Integer(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('period', sa.Integer(), nullable=False),
    sa.Column('model', sa.String(length=60), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('auto', sa.Boolean(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('freelancer_bid_id', sa.BigInteger(), nullable=True),
    sa.Column('bid_status', sa.String(length=30), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prompt_id'], ['prompts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id')
    )
    op.create_index(op.f('ix_proposals_sent_at'), 'proposals', ['sent_at'], unique=False)
    op.create_index(op.f('ix_proposals_status'), 'proposals', ['status'], unique=False)

    # Supabase exposes the public schema through its Data API. Row level security with no
    # policies closes that door; the backend connects as the table owner, which bypasses it.
    for table in TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_proposals_status'), table_name='proposals')
    op.drop_index(op.f('ix_proposals_sent_at'), table_name='proposals')
    op.drop_table('proposals')
    op.drop_index(op.f('ix_prompts_kind'), table_name='prompts')
    op.drop_table('prompts')
    op.drop_index(op.f('ix_projects_status'), table_name='projects')
    op.drop_index(op.f('ix_projects_created_at'), table_name='projects')
    op.drop_table('projects')
    op.drop_table('profile_items')
    op.drop_index(op.f('ix_event_logs_event'), table_name='event_logs')
    op.drop_index(op.f('ix_event_logs_created_at'), table_name='event_logs')
    op.drop_table('event_logs')
    op.drop_table('app_config')
