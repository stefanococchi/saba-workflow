"""Add user_audit_log table

Revision ID: r8m9n0o1p2q3
Revises: q7l8m9n0o1p2
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'r8m9n0o1p2q3'
down_revision = 'q7l8m9n0o1p2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('user_email', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('entity', sa.String(length=50), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_audit_log_timestamp', 'user_audit_log', ['timestamp'])
    op.create_index('ix_user_audit_log_action', 'user_audit_log', ['action'])


def downgrade():
    op.drop_index('ix_user_audit_log_action', table_name='user_audit_log')
    op.drop_index('ix_user_audit_log_timestamp', table_name='user_audit_log')
    op.drop_table('user_audit_log')
