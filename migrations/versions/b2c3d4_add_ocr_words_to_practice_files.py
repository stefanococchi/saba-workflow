"""add ocr_words to practice_files

Revision ID: b2c3d4ocr002
Revises: a1b2c3ocr001
Create Date: 2026-05-24

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4ocr002'
down_revision = 'a1b2c3ocr001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('practice_files', sa.Column('ocr_words', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('practice_files', 'ocr_words')
