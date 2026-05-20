"""add practice_results table

Revision ID: v1w2x3y4z5a6
Revises: u1p2q3r4s5t6
Create Date: 2026-05-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'v1w2x3y4z5a6'
down_revision = 'u1p2q3r4s5t6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('practice_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('practice_id', sa.String(length=255), nullable=False),
        sa.Column('agent_id', sa.String(length=255), nullable=False),
        sa.Column('agent_name', sa.String(length=255), nullable=True),
        sa.Column('result_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_practice_results_practice_id', 'practice_results', ['practice_id'], unique=True)


def downgrade():
    op.drop_index('ix_practice_results_practice_id', table_name='practice_results')
    op.drop_table('practice_results')
