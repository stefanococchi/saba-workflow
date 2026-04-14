"""Add sabaform event fields to workflows

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflows', sa.Column('sabaform_event_id', sa.Integer(), nullable=True))
    op.add_column('workflows', sa.Column('sabaform_event_name', sa.String(length=300), nullable=True))


def downgrade():
    op.drop_column('workflows', 'sabaform_event_name')
    op.drop_column('workflows', 'sabaform_event_id')
