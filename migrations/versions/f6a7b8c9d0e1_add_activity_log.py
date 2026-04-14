"""Add activity_log table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('activity_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('workflows.id'), nullable=False),
        sa.Column('participant_id', sa.Integer(), sa.ForeignKey('participants.id'), nullable=True),
        sa.Column('step_id', sa.Integer(), sa.ForeignKey('workflow_steps.id'), nullable=True),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('details', sa.JSON()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_activity_log_workflow_id', 'activity_log', ['workflow_id'])
    op.create_index('ix_activity_log_created_at', 'activity_log', ['created_at'])


def downgrade():
    op.drop_table('activity_log')
