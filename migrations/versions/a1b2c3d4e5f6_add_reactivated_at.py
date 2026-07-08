"""add reactivated_at to participants

Revision ID: a1b2c3d4e5f6
Revises: z5a6b7c8d9e0
Create Date: 2026-07-08

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('participants', sa.Column('reactivated_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('participants', 'reactivated_at')
