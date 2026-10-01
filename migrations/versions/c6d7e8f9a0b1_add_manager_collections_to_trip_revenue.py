"""Add manager-collected revenue to outbound and return trips

Revision ID: c6d7e8f9a0b1
Revises: f5a6b7c8d9e0
Create Date: 2026-10-01

"""
from alembic import op
import sqlalchemy as sa

revision = 'c6d7e8f9a0b1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.add_column(
            sa.Column(
                'manager_revenue_collected',
                sa.Numeric(precision=12, scale=2),
                nullable=False,
                server_default='0',
            )
        )

    with op.batch_alter_table('phoi_return_trips') as batch_op:
        batch_op.add_column(
            sa.Column(
                'manager_revenue_collected',
                sa.Numeric(precision=12, scale=2),
                nullable=False,
                server_default='0',
            )
        )


def downgrade():
    with op.batch_alter_table('phoi_return_trips') as batch_op:
        batch_op.drop_column('manager_revenue_collected')

    with op.batch_alter_table('phoi') as batch_op:
        batch_op.drop_column('manager_revenue_collected')
