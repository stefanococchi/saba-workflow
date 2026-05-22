"""add ao_agent_id to workflows

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
Create Date: 2026-05-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'z5a6b7c8d9e0'
down_revision = 'y4z5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflows', sa.Column('ao_agent_id', sa.String(255), nullable=True))
    op.add_column('workflows', sa.Column('ao_agent_name', sa.String(255), nullable=True))


def downgrade():
    op.drop_column('workflows', 'ao_agent_name')
    op.drop_column('workflows', 'ao_agent_id')
