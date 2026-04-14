"""Add CASCADE to activity_log foreign keys

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-04-14

"""
from alembic import op

revision = 'h8c9d0e1f2g3'
down_revision = 'g7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    # workflow_id
    op.drop_constraint('activity_log_workflow_id_fkey', 'activity_log', type_='foreignkey')
    op.create_foreign_key('activity_log_workflow_id_fkey', 'activity_log', 'workflows',
                          ['workflow_id'], ['id'], ondelete='CASCADE')
    # participant_id
    op.drop_constraint('activity_log_participant_id_fkey', 'activity_log', type_='foreignkey')
    op.create_foreign_key('activity_log_participant_id_fkey', 'activity_log', 'participants',
                          ['participant_id'], ['id'], ondelete='CASCADE')
    # step_id
    op.drop_constraint('activity_log_step_id_fkey', 'activity_log', type_='foreignkey')
    op.create_foreign_key('activity_log_step_id_fkey', 'activity_log', 'workflow_steps',
                          ['step_id'], ['id'], ondelete='CASCADE')


def downgrade():
    op.drop_constraint('activity_log_workflow_id_fkey', 'activity_log', type_='foreignkey')
    op.create_foreign_key('activity_log_workflow_id_fkey', 'activity_log', 'workflows',
                          ['workflow_id'], ['id'])
    op.drop_constraint('activity_log_participant_id_fkey', 'activity_log', type_='foreignkey')
    op.create_foreign_key('activity_log_participant_id_fkey', 'activity_log', 'participants',
                          ['participant_id'], ['id'])
    op.drop_constraint('activity_log_step_id_fkey', 'activity_log', type_='foreignkey')
    op.create_foreign_key('activity_log_step_id_fkey', 'activity_log', 'workflow_steps',
                          ['step_id'], ['id'])
