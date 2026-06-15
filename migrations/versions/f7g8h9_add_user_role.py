"""Add role field to users table

Revision ID: f7g8h9role01
Revises: e5f6g7sso001
Create Date: 2026-06-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'f7g8h9role01'
down_revision = 'e5f6g7sso001'
branch_labels = None
depends_on = None


def upgrade():
    # Create enum type
    role_enum = sa.Enum('superuser', 'user', 'client', name='userrole')
    role_enum.create(op.get_bind(), checkfirst=True)

    # Add role column with default 'user'
    op.add_column('users', sa.Column('role', role_enum, nullable=False, server_default='user'))

    # Sync existing superusers: set role='superuser' where is_superuser=True
    op.execute("UPDATE users SET role = 'superuser' WHERE is_superuser = 1")


def downgrade():
    op.drop_column('users', 'role')
    sa.Enum(name='userrole').drop(op.get_bind(), checkfirst=True)
