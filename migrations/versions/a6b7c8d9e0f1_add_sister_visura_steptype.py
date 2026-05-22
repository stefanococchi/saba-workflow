"""add sister_visura step type

Revision ID: a6b7c8d9e0f1
Revises: z5a6b7c8d9e0
Create Date: 2026-05-22

"""
from alembic import op

revision = 'a6b7c8d9e0f1'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'SISTER_VISURA'")


def downgrade():
    pass
