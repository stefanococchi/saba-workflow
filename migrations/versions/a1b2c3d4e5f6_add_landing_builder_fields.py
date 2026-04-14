"""Add landing builder fields to workflow_steps

Revision ID: a1b2c3d4e5f6
Revises: 68cb41d7da7d
Create Date: 2026-04-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '68cb41d7da7d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflow_steps', sa.Column('landing_html', sa.Text(), nullable=True))
    op.add_column('workflow_steps', sa.Column('landing_css', sa.Text(), nullable=True))
    op.add_column('workflow_steps', sa.Column('landing_gjs_data', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('workflow_steps', 'landing_gjs_data')
    op.drop_column('workflow_steps', 'landing_css')
    op.drop_column('workflow_steps', 'landing_html')
