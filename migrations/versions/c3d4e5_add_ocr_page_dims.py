"""add ocr_page_dims to practice_files

Revision ID: c3d4e5ocr003
Revises: b2c3d4ocr002
Create Date: 2026-05-26

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5ocr003'
down_revision = 'b2c3d4ocr002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('practice_files', sa.Column('ocr_page_dims', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('practice_files', 'ocr_page_dims')
