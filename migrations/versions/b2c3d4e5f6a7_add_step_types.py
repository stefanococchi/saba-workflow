"""Add new step types to steptype enum

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-13

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Add new values to the steptype enum
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'WAIT_UNTIL'")
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'GOAL_CHECK'")
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'EXPORT_DATA'")
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'CONDITION'")


def downgrade():
    # PostgreSQL doesn't support removing enum values easily
    pass
