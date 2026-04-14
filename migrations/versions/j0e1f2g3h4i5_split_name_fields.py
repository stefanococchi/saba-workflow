"""Split participant name into first_name and last_name

Revision ID: j0e1f2g3h4i5
Revises: i9d0e1f2g3h4
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'j0e1f2g3h4i5'
down_revision = 'i9d0e1f2g3h4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('participants', sa.Column('first_name', sa.String(100)))
    op.add_column('participants', sa.Column('last_name', sa.String(100)))

    # Migra dati: splitta name in first_name + last_name
    op.execute("""
        UPDATE participants
        SET first_name = CASE
                WHEN name LIKE '% %' THEN SUBSTRING(name FROM 1 FOR POSITION(' ' IN name) - 1)
                ELSE name
            END,
            last_name = CASE
                WHEN name LIKE '% %' THEN SUBSTRING(name FROM POSITION(' ' IN name) + 1)
                ELSE ''
            END
        WHERE name IS NOT NULL
    """)

    op.drop_column('participants', 'name')


def downgrade():
    op.add_column('participants', sa.Column('name', sa.String(200)))
    op.execute("""
        UPDATE participants
        SET name = TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, ''))
        WHERE first_name IS NOT NULL OR last_name IS NOT NULL
    """)
    op.drop_column('participants', 'first_name')
    op.drop_column('participants', 'last_name')
