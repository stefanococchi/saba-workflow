"""Add payment_log table for Stripe payment audit trail

Revision ID: u1p2q3r4s5t6
Revises: t0o1p2q3r4s5
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'u1p2q3r4s5t6'
down_revision = 't0o1p2q3r4s5'
branch_labels = None
depends_on = None


def upgrade():
    payment_status = sa.Enum(
        'initiated', 'completed', 'failed', 'expired', 'cancelled', 'refunded', 'disputed',
        name='paymentstatus'
    )
    payment_status.create(op.get_bind(), checkfirst=True)

    op.create_table('payment_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('participant_id', sa.Integer(),
                   sa.ForeignKey('participants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_id', sa.Integer(),
                   sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_id', sa.Integer(),
                   sa.ForeignKey('workflow_steps.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stripe_session_id', sa.String(255), nullable=True),
        sa.Column('stripe_payment_intent_id', sa.String(255), nullable=True),
        sa.Column('stripe_event_id', sa.String(255), nullable=True, unique=True),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='eur'),
        sa.Column('status', payment_status, nullable=False),
        sa.Column('stripe_event_type', sa.String(100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('raw_event', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_payment_log_participant_id', 'payment_log', ['participant_id'])
    op.create_index('ix_payment_log_workflow_id', 'payment_log', ['workflow_id'])
    op.create_index('ix_payment_log_step_id', 'payment_log', ['step_id'])
    op.create_index('ix_payment_log_participant_step', 'payment_log', ['participant_id', 'step_id'])
    op.create_index('ix_payment_log_stripe_session', 'payment_log', ['stripe_session_id'])
    op.create_index('ix_payment_log_status', 'payment_log', ['status'])
    op.create_index('ix_payment_log_created_at', 'payment_log', ['created_at'])


def downgrade():
    op.drop_table('payment_log')
    sa.Enum(name='paymentstatus').drop(op.get_bind(), checkfirst=True)
