"""Add attachments table

Revision ID: o5j6k7l8m9n0
Revises: n4i5j6k7l8m9
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'o5j6k7l8m9n0'
down_revision = 'n4i5j6k7l8m9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'attachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('attachments')
