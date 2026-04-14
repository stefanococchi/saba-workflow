"""Add landing_templates table

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = 'i9d0e1f2g3h4'
down_revision = 'h8c9d0e1f2g3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('landing_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('landing_html', sa.Text()),
        sa.Column('landing_css', sa.Text()),
        sa.Column('landing_gjs_data', JSON),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('landing_templates')
