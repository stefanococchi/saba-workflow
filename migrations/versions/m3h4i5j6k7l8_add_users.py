"""Add users and user_workflows tables

Revision ID: m3h4i5j6k7l8
Revises: l2g3h4i5j6k7
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'm3h4i5j6k7l8'
down_revision = 'l2g3h4i5j6k7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username')
    )
    op.create_table('user_workflows',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'workflow_id')
    )


def downgrade():
    op.drop_table('user_workflows')
    op.drop_table('users')
