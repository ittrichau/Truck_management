"""Add customer to PHOI return trips

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa


revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi_return_trips') as batch_op:
        batch_op.add_column(sa.Column('customer_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_phoi_return_trips_customer_id_customers',
            'customers',
            ['customer_id'],
            ['id']
        )


def downgrade():
    with op.batch_alter_table('phoi_return_trips') as batch_op:
        batch_op.drop_constraint('fk_phoi_return_trips_customer_id_customers', type_='foreignkey')
        batch_op.drop_column('customer_id')
