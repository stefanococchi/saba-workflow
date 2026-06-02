"""add sister_ipotecaria step type

Revision ID: b7c8d9e0f1g2
Revises: a6b7c8d9e0f1
Create Date: 2026-06-02

"""
from alembic import op

revision = 'b7c8d9e0f1g2'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'SISTER_IPOTECARIA'")


def downgrade():
    pass
