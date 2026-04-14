"""Add token_expiration_hours to workflows

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflows', sa.Column('token_expiration_hours', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('workflows', 'token_expiration_hours')
