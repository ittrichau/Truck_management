"""Preserve three decimal places for fuel liters.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-09

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    # Retain the existing ten integer digits while adding a fractional digit.
    with op.batch_alter_table('fuel_logs') as batch_op:
        batch_op.alter_column(
            'liters', existing_type=sa.Numeric(12, 2),
            type_=sa.Numeric(13, 3), existing_nullable=False,
        )


def downgrade():
    fuel_logs = sa.table('fuel_logs', sa.column('liters', sa.Numeric(13, 3)))
    has_extra_precision = op.get_bind().execute(
        sa.select(fuel_logs.c.liters)
        .where(fuel_logs.c.liters != sa.func.round(fuel_logs.c.liters, 2))
        .limit(1)
    ).first()
    if has_extra_precision:
        raise RuntimeError(
            'Cannot downgrade: fuel liters would lose decimal precision. '
            'Back up and explicitly resolve three-decimal values first.'
        )
    with op.batch_alter_table('fuel_logs') as batch_op:
        batch_op.alter_column(
            'liters', existing_type=sa.Numeric(13, 3),
            type_=sa.Numeric(12, 2), existing_nullable=False,
        )
