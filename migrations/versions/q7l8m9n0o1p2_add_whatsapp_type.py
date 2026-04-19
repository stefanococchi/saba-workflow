"""Add whatsapp step type

Revision ID: q7l8m9n0o1p2
Revises: p6k7l8m9n0o1
Create Date: 2026-04-19
"""
from alembic import op

revision = 'q7l8m9n0o1p2'
down_revision = 'p6k7l8m9n0o1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'WHATSAPP'")


def downgrade():
    pass
