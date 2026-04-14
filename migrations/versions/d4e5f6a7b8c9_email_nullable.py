"""Make participant email nullable

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('participants', 'email', existing_type=sa.String(255), nullable=True)


def downgrade():
    op.alter_column('participants', 'email', existing_type=sa.String(255), nullable=False)
