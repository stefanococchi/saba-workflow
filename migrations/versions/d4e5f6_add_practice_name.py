"""add name to practice_results

Revision ID: d4e5f6name01
Revises: c3d4e5ocr003
Create Date: 2026-06-04

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6name01'
down_revision = 'c3d4e5ocr003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('practice_results', sa.Column('name', sa.String(255), nullable=True))


def downgrade():
    op.drop_column('practice_results', 'name')
