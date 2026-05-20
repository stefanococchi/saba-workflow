"""add practice_files table

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-05-20

"""
from alembic import op
import sqlalchemy as sa

revision = 'w2x3y4z5a6b7'
down_revision = 'v1w2x3y4z5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('practice_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('practice_id', sa.String(length=255), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_practice_files_practice_id', 'practice_files', ['practice_id'])


def downgrade():
    op.drop_index('ix_practice_files_practice_id', table_name='practice_files')
    op.drop_table('practice_files')
