"""add ocr_text to practice_files

Revision ID: a1b2c3ocr001
Revises: z5a6b7c8d9e0
Create Date: 2026-05-24

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3ocr001'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('practice_files', sa.Column('ocr_text', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('practice_files', 'ocr_text')
