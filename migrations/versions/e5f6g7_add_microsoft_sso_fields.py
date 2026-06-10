"""Add Microsoft SSO fields to users table

Revision ID: e5f6g7sso001
Revises: d4e5f6name01
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6g7sso001'
down_revision = 'd4e5f6name01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('microsoft_id', sa.String(100), unique=True, nullable=True))
    op.add_column('users', sa.Column('ms_access_token', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('ms_refresh_token', sa.Text(), nullable=True))
    # Make password nullable (SSO-only users don't need a password)
    op.alter_column('users', 'password_hash', existing_type=sa.String(255), nullable=True)


def downgrade():
    op.alter_column('users', 'password_hash', existing_type=sa.String(255), nullable=False)
    op.drop_column('users', 'ms_refresh_token')
    op.drop_column('users', 'ms_access_token')
    op.drop_column('users', 'microsoft_id')
