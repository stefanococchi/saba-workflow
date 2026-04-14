"""Add sabaform_data JSON column to participants

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = 'g7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('participants', sa.Column('sabaform_data', JSON, server_default='{}'))


def downgrade():
    op.drop_column('participants', 'sabaform_data')
