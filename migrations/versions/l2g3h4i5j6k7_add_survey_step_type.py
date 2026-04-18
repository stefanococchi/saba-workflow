"""Add survey step type

Revision ID: l2g3h4i5j6k7
Revises: k1f2g3h4i5j6
Create Date: 2026-04-17
"""
from alembic import op

# revision identifiers
revision = 'l2g3h4i5j6k7'
down_revision = 'k1f2g3h4i5j6'
branch_labels = None
depends_on = None


def upgrade():
    # Add 'survey' to the steptype enum
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'SURVEY'")


def downgrade():
    # PostgreSQL doesn't support removing enum values easily
    pass
