"""add payment methods to phoi

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c8d9e0f1a2'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.add_column(sa.Column('payment_method', sa.String(length=20), nullable=False, server_default='fixed'))
        batch_op.add_column(sa.Column('price_per_ton', sa.Numeric(precision=12, scale=2), nullable=True))

    with op.batch_alter_table('phoi_return_trips') as batch_op:
        batch_op.add_column(sa.Column('cargo_weight_tons', sa.Numeric(precision=10, scale=3), nullable=True))
        batch_op.add_column(sa.Column('payment_method', sa.String(length=20), nullable=False, server_default='fixed'))
        batch_op.add_column(sa.Column('price_per_ton', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade():
    with op.batch_alter_table('phoi_return_trips') as batch_op:
        batch_op.drop_column('price_per_ton')
        batch_op.drop_column('payment_method')
        batch_op.drop_column('cargo_weight_tons')

    with op.batch_alter_table('phoi') as batch_op:
        batch_op.drop_column('price_per_ton')
        batch_op.drop_column('payment_method')
