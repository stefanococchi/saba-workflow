"""Add performance indexes on foreign keys and frequently filtered columns

Revision ID: t0o1p2q3r4s5
Revises: s9n0o1p2q3r4
Create Date: 2026-04-24
"""
from alembic import op
from sqlalchemy import text

revision = 't0o1p2q3r4s5'
down_revision = 's9n0o1p2q3r4'
branch_labels = None
depends_on = None


def _create_index_if_not_exists(name, table, columns):
    """Create index only if it doesn't already exist (PostgreSQL)."""
    cols = ', '.join(columns)
    op.execute(text(
        f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})'
    ))


def upgrade():
    # participants — FK and status lookups
    _create_index_if_not_exists('ix_participants_workflow_id', 'participants', ['workflow_id'])
    _create_index_if_not_exists('ix_participants_status', 'participants', ['status'])
    _create_index_if_not_exists('ix_participants_enrolled_at', 'participants', ['enrolled_at'])

    # workflow_steps — FK lookup
    _create_index_if_not_exists('ix_workflow_steps_workflow_id', 'workflow_steps', ['workflow_id'])

    # executions — FK lookups, status filter, scheduling order
    _create_index_if_not_exists('ix_executions_participant_id', 'executions', ['participant_id'])
    _create_index_if_not_exists('ix_executions_step_id', 'executions', ['step_id'])
    _create_index_if_not_exists('ix_executions_status', 'executions', ['status'])
    _create_index_if_not_exists('ix_executions_scheduled_at', 'executions', ['scheduled_at'])

    # activity_log — FK lookups and time ordering
    _create_index_if_not_exists('ix_activity_log_workflow_id', 'activity_log', ['workflow_id'])
    _create_index_if_not_exists('ix_activity_log_participant_id', 'activity_log', ['participant_id'])
    _create_index_if_not_exists('ix_activity_log_created_at', 'activity_log', ['created_at'])


def downgrade():
    op.drop_index('ix_activity_log_created_at', table_name='activity_log')
    op.drop_index('ix_activity_log_participant_id', table_name='activity_log')
    op.drop_index('ix_activity_log_workflow_id', table_name='activity_log')
    op.drop_index('ix_executions_scheduled_at', table_name='executions')
    op.drop_index('ix_executions_status', table_name='executions')
    op.drop_index('ix_executions_step_id', table_name='executions')
    op.drop_index('ix_executions_participant_id', table_name='executions')
    op.drop_index('ix_workflow_steps_workflow_id', table_name='workflow_steps')
    op.drop_index('ix_participants_enrolled_at', table_name='participants')
    op.drop_index('ix_participants_status', table_name='participants')
    op.drop_index('ix_participants_workflow_id', table_name='participants')
