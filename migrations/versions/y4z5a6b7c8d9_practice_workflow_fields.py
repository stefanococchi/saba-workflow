"""add workflow fields to practice_results

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
Create Date: 2026-05-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'y4z5a6b7c8d9'
down_revision = 'x3y4z5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('practice_results', sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('workflows.id'), nullable=True))
    op.add_column('practice_results', sa.Column('current_step_order', sa.Integer(), nullable=True))
    op.add_column('practice_results', sa.Column('step_states', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('practice_results', 'step_states')
    op.drop_column('practice_results', 'current_step_order')
    op.drop_column('practice_results', 'workflow_id')
