"""add document_check step type

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-05-22

"""
from alembic import op

revision = 'x3y4z5a6b7c8'
down_revision = 'w2x3y4z5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE steptype ADD VALUE IF NOT EXISTS 'document_check'")


def downgrade():
    pass
