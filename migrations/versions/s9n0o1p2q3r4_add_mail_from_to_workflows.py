"""Add mail_from_email and mail_from_name to workflows

Revision ID: s9n0o1p2q3r4
Revises: r8m9n0o1p2q3
Create Date: 2026-04-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 's9n0o1p2q3r4'
down_revision = 'r8m9n0o1p2q3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflows', sa.Column('mail_from_email', sa.String(length=300), nullable=True))
    op.add_column('workflows', sa.Column('mail_from_name', sa.String(length=300), nullable=True))


def downgrade():
    op.drop_column('workflows', 'mail_from_name')
    op.drop_column('workflows', 'mail_from_email')
