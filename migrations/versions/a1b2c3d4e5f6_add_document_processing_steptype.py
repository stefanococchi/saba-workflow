"""add document_processing step type

Revision ID: a1b2c3d4e5f6
Revises: z5a6b7c8d9e0
Create Date: 2026-05-23

"""
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'DOCUMENT_PROCESSING'")


def downgrade():
    pass
