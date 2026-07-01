"""add completion_type to participants

Revision ID: a1b2c3d4e5f6
Revises: z5a6b7c8d9e0
Create Date: 2026-07-01

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    completion_type_enum = sa.Enum('participated', 'expired', name='completiontype')
    completion_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column('participants', sa.Column('completion_type', completion_type_enum, nullable=True))

    # Backfill existing completed participants:
    # If collected_data has content (not null, not empty '{}') → participated, else → expired
    op.execute("""
        UPDATE participants
        SET completion_type = CASE
            WHEN collected_data IS NOT NULL
                 AND collected_data != 'null'
                 AND collected_data != '{}'
                 AND CAST(collected_data AS TEXT) != '{}'
            THEN 'participated'
            ELSE 'expired'
        END
        WHERE status = 'completed'
    """)


def downgrade():
    op.drop_column('participants', 'completion_type')
    sa.Enum(name='completiontype').drop(op.get_bind(), checkfirst=True)
