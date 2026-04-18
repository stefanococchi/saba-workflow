"""Add human_approval step type

Revision ID: n4i5j6k7l8m9
Revises: m3h4i5j6k7l8
Create Date: 2026-04-17
"""
from alembic import op

revision = 'n4i5j6k7l8m9'
down_revision = 'm3h4i5j6k7l8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'HUMAN_APPROVAL'")


def downgrade():
    pass
